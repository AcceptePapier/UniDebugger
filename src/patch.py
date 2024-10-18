import os
import logging
import re
import subprocess
import docker
import signal
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.parse import *

class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("TimeOut")

class NotPatchError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message
        print(message)

def format_patch_lines(patch: str) -> list[str]:
    return re.compile(r'(@@[\s\d\+\-\,]+@@)(\s+[a-zA-Z]+)').sub(r'\1\n\2', patch).splitlines()

def format_code(code_lines: list[str]) -> list[str]: #rule-based nomarlization
    for code_idx, line in enumerate(code_lines):
        concat = False
        for k in ["public, private", "protected"]: 
            if line.replace(" ", "") == k:
                concat = True
                code_lines[code_idx] = ""
                code_lines[code_idx + 1] = k + " " + code_lines[code_idx + 1].lstrip()
                break
        
        if not concat and code_idx < len(code_lines) - 1 and not ("class" in line) and \
            (not line.strip().startswith("*")) and ("//" not in line and "/*" not in line) and \
            re.search("r'[a-zA-Z0-9]$'", line):
            print("![concat]!", code_idx, code_lines[code_idx].rstrip(), "<+>", code_lines[code_idx + 1].lstrip())
            code_lines[code_idx] = line.rstrip() + " " + code_lines[code_idx + 1].lstrip()
            code_lines[code_idx + 1] = ""
    
    return code_lines

def is_a_patch(patch_lines: list[str]) -> bool:
    a = any(re.match(r'^@@\s-\d+,\d+\s\+\d+,\d+\s@@.*', line.strip()) for line in patch_lines)
    if not a:
        print("$$$$$ no @@")
        print("\n".join(patch_lines))
        return False
    b = any(re.match(r'^[-+](\s|\t)+.*$', line.strip()) for line in patch_lines)
    if not b:
        print("$$$$$ no -+")
        print("\n".join(patch_lines))
        return False
    return a and b
        
def find_a_matched_line(pidx: int, pline: str, code_lines: list[str], patch_lines: list[str], lag=-1) -> int:
    matched = matching_lines(pline, code_lines)
    if lag >= 0:
        matched = [m for m in matched if m > lag]
    if len(matched) == 1:
        return matched[0]
    
    match_perfect = matching_with_comments(pline, matched, code_lines) # Consider comments
    if len(match_perfect) == 1:
        return match_perfect[0]

    return unique_matching(patch_lines, code_lines, pidx)


def patching(patch: str, raw_code_lines: list[str]) -> str: # return patched code
    patch_lines = format_patch_lines(patch)
    if not is_a_patch(patch_lines):
        raise NoCodeError(f"Not a patch!\n{patch}")
    assert isinstance(raw_code_lines, list)
    
    code_lines = format_code(raw_code_lines)
    # chg: old line -> new line
    # del: old line -> ''
    # add: old line -> old line \n added_line
    patched = {i: l for i, l in enumerate(code_lines)} # return patched code
    unpatched_lines = []
    to_patch_num = 0
    replace_idx, pre_patch_idx = None, None #record the previous position of modification
    
    for pidx, pline in enumerate(patch_lines):
        if re.search(r'^[-](\s|\t)+.*$', pline): # del sth
            to_patch_num += 1
            if pre_patch_idx is not None and pre_patch_idx + 1 == pidx and patch_lines[pre_patch_idx][0] == '-': #前一个位置也是-，即连续删除
                    patched[replace_idx + 1] = ""
                    replace_idx, pre_patch_idx = replace_idx + 1, pidx
            else:
                match_idx = find_a_matched_line(pidx, pline[1:].lstrip(), code_lines, patch_lines, lag=replace_idx)
                if match_idx > 0:
                    patched[match_idx] = ""
                    replace_idx, pre_patch_idx = match_idx, pidx
                else:
                    logging.warning(f"Cannot patch {pline}!")
                    unpatched_lines.append((pidx, pline))
        elif re.search(r'^[+](\s|\t)+.*$', pline): # add sth
            to_patch_num += 1
            if pre_patch_idx is not None and pre_patch_idx + 1 == pidx: # some changes on just the last line
                if patch_lines[pre_patch_idx][0] == '-': # pre is -, cur is +, meaning cur line replaces pre line
                    patched[replace_idx] = pline[1:].rstrip()
                elif patch_lines[pre_patch_idx][0] == '+': #pre is +，cur is +，meaning using multi lines to replace a pre line
                    patched[replace_idx] += ("\n" + pline[1:].rstrip())
                pre_patch_idx = pidx
            else: # directly adding
                if pidx > 0:
                    match_idx = find_a_matched_line(pidx, pline[1:].lstrip(), code_lines, patch_lines, lag=replace_idx)
                    print("\%\%\%", patch_lines[pidx-1], match_idx)
                    if match_idx >= 0:
                        patched[match_idx] += ("\n" + pline[1:].rstrip())
                        replace_idx, pre_patch_idx = match_idx, pidx
                        continue
                if pidx < len(patch_lines) - 1: 
                    match_idx = find_a_matched_line(pidx, pline[1:].lstrip(), code_lines, patch_lines, lag=replace_idx)
                    if match_idx >= 0:
                        patched[match_idx] = pline[1:].rstrip() + "\n" + patched[match_idx]
                        replace_idx, pre_patch_idx = match_idx, pidx
                        continue
                # Cannot find neibors
                logging.warning(f"Cannot patch! {pline}")
                unpatched_lines.append((pidx, pline))
    
    if len(unpatched_lines) == to_patch_num:
        raise NotPatchError("")
    
    if len(unpatched_lines) > 0:
        for (pidx, pline) in unpatched_lines:
            print(f"#{pidx}\t{pline}")
    
    return "\n".join([patched[i] for i in range(len(code_lines)) if len(patched[i]) > 0])


def testing(root_test_dir: str, container)-> int: # return the number of failing test cases
    env_vars = {'JAVA_TOOL_OPTIONS': '-Dfile.encoding=UTF8'}
    logging.info("# Compiling...")
    compile_result = container.exec_run("sh -c 'export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-arm64 && defects4j compile'", 
                                        workdir=root_test_dir, environment=env_vars).output.decode('utf-8')
    if "BUILD FAILED" in compile_result:
        logging.warning(f"Compile Failed\n{compile_result}")
        return -1
    
    logging.info("# Testing...")
    signal.signal(signal.SIGALRM, timeout_handler)  
    signal.alarm(5*60)
    try:
        test_result = container.exec_run("sh -c 'export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-arm64 && defects4j test'", 
                                     workdir=root_test_dir, stderr=True, stdout=True).output.decode('utf-8')
        signal.alarm(0)
    except TimeoutException:
        logging.warning("Timeout!")
        return -1
    except Exception as e:
        logging.error(f"Errors during testing: {e}")

    re_match = re.search(r'Failing tests:\s*(\d+)', test_result)
    if re_match:
        os.remove("buggy.java"); os.remove("patched.java")
        return int(re_match.group(1))
    else:
        logging.error(f"Test results\n{test_result}")
        print("@"*50)
        exit()
    
def patching_and_testing(patch: str, project_meta: dict, container_id='7bdc33a65712') -> bool: # Pass testing?
    client = docker.from_env()
    container = client.containers.get(container_id)
    
    
    main_dir = "/defects4j"
    bug_name = project_meta['project_name'] + "_" + str(project_meta['buggy_number'])
    project_dir = os.path.join(project_meta['checkout_dir'], f"{bug_name}_buggy")

    logging.info("# Checking out...")
    container.exec_run(f"rm -rf {project_dir}", workdir=main_dir)
    container.exec_run(f"defects4j checkout -p {project_meta['project_name']} -v {project_meta['buggy_number']}b -w {project_dir}", workdir=main_dir)
    
    code_undecode = container.exec_run(f"cat {project_meta['buggy_file_path']}", workdir=main_dir).output # buggy code
    try:
        buggy_code = code_undecode.decode('utf-8')
    except UnicodeDecodeError:
        buggy_code = code_undecode.decode('latin-1')
    with open(f"buggy.java", "w") as wf:
        wf.write(buggy_code)

    logging.info("# Getting patched code...")
    try:
        patched_code = patching(patch, buggy_code.splitlines())
    except (NoCodeError, NotPatchError) as e:
        logging.warning(f"Cannot patch this patch because {e}")
        return None
    with open(f"patched.java", "w") as wf:
        wf.write(patched_code)
    
    logging.info("# Patching back...") # copy patched code to container
    subprocess.run(["docker", "cp", f"patched.java", f"{container_id}:"+os.path.join(main_dir, project_meta['buggy_file_path'])], check=True)
    
    return testing(os.path.join(main_dir, project_dir), container) == 0



