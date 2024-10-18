import os
import logging
import re
import subprocess
import signal
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parse import *

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
        
def find_a_matched_line(pidx: int, pline: str, code_lines: list[str], patch_lines: list[str], lag=-1, existing=False) -> int:
    matched = matching_lines(pline, code_lines)
    if lag >= 0:
        matched = [m for m in matched if m > lag]
    if len(matched) == 1:
        return matched[0]
    
    match_perfect = matching_with_comments(pline, matched, code_lines) # Consider comments
    if len(match_perfect) == 1:
        return match_perfect[0]

    return unique_matching(patch_lines, code_lines, pidx, resp_cur_line=pline, existing=existing)


def patching(patch: str, raw_code_lines: list[str]) -> str: # return patched code
    patch_lines = format_patch_lines(patch)
    if not is_a_patch(patch_lines):
        raise NoCodeError(f"Not a patch!\n{patch}")
    assert isinstance(raw_code_lines, list)
    
    code_lines = format_code(raw_code_lines)
    # chg: old line -> new line
    # del: old line -> ''
    # add: old line -> old line \n added_line
    patched = [l for l in code_lines] # return patched code
    unpatched_lines = []
    to_patch_num = 0
    replace_idx, pre_patch_idx = -1, -1 #record the previous position of modification

    for pidx, pline in enumerate(patch_lines):
        if re.search(r'^[-](\s|\t)+.*$', pline): # del sth
            to_patch_num += 1
            if pre_patch_idx >= 0 and pre_patch_idx + 1 == pidx and patch_lines[pre_patch_idx][0] == '-': #del multi lines
                    patched[replace_idx + 1] = ""
                    replace_idx, pre_patch_idx = replace_idx + 1, pidx
            else:
                match_idx = find_a_matched_line(pidx, pline[1:].lstrip(), code_lines, patch_lines, lag=replace_idx, existing=True)
                if match_idx > 0:
                    patched[match_idx] = ""
                    replace_idx, pre_patch_idx = match_idx, pidx
                else:
                    logging.warning(f"Cannot patch {pline}!")
                    unpatched_lines.append((pidx, pline))
        elif re.search(r'^[+](\s|\t)+.*$', pline): # add sth
            to_patch_num += 1
            if pre_patch_idx >= 0 and pre_patch_idx + 1 == pidx: # some changes on just the last line
                if patch_lines[pre_patch_idx][0] == '-': # pre is -, cur is +, meaning cur line replaces pre line
                    patched[replace_idx] = pline[1:].rstrip()
                elif patch_lines[pre_patch_idx][0] == '+': #pre is +，cur is +，meaning using multi lines to replace a pre line
                    if isinstance(patched[replace_idx], str):
                        patched[replace_idx] += ("\n" + pline[1:].rstrip())
                    elif isinstance(patched[replace_idx], list):
                        patched[replace_idx] = patched[replace_idx][:-1] + [pline[1:].rstrip(), patched[replace_idx][-1]]
                    else:
                        raise TypeError(f"{patched[replace_idx]} in unsupported type {type(patched[replace_idx])}")
                pre_patch_idx = pidx
            else: # directly adding
                print("\n--> Patch + this", patch_lines[pidx], "\n")
                # can the previous valid line has a match?
                pre_valid = search_valid_line(patch_lines, pidx, "pre")
                if pre_valid is not None:
                    unique_idx = find_a_matched_line(pre_valid[0], pre_valid[1], code_lines, patch_lines, lag=replace_idx)
                    if unique_idx >= 0:
                        patched[unique_idx] += ("\n" + pline[1:].rstrip())
                        replace_idx, pre_patch_idx = unique_idx, pidx
                        continue
                post_valid = search_valid_line(patch_lines, pidx, "post", existing=code_lines)
                if post_valid is not None:
                    unique_idx = find_a_matched_line(post_valid[0], post_valid[1], code_lines, patch_lines, lag=replace_idx)
                    if unique_idx >= 0:
                        patched[unique_idx] = [pline[1:].rstrip(), patched[unique_idx]]
                        replace_idx, pre_patch_idx = unique_idx, pidx
                        continue
                # Cannot find neibors
                logging.warning(f"Cannot patch! {pline}")
                unpatched_lines.append((pidx, pline))
    
    if len(unpatched_lines) == to_patch_num:
        raise NotPatchError("")
    
    if len(unpatched_lines) > 0:
        for (pidx, pline) in unpatched_lines:
            print(f"Unpatched lines: #{pidx}\t{pline}")
    
    res = ""
    for p in patched:
        if len(p) == 0: continue
        if isinstance(p, str):
            res += "\n" + p
        elif isinstance(p, list):
            res += "\n" + "\n".join(p)
        else:
            raise TypeError(f"{p} in unsupported type {type(p)}")
    return res.strip()


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
    import docker
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

if __name__ == "__main__":
    patch = '''
    @@ -941,7 +941,7 @@
-   head
+   add_0 // missing code
+   add_1 
+   add_2
+   add_3
    post neibor, degree == 1
    post neibor, degree == 2
    post neibor, degree == 3
    post neibor, degree == 4
    post neibor, degree == 5
    end
    '''
    raw_code = '''
    head
    post neibor, degree == 1
    post neibor, degree == 2
    post neibor, degree == 3
    post neibor, degree == 4
    post neibor, degree == 5
    end
    ==================
    head
    post neibor, degree == 1
    post neibor, degree == 2
    post neibor, degree == 3
    post neibor, degree == 4
    end
    ==================
    head
    pre neibor, degree == 3
    pre neibor, degree == 2
    pre neibor, degree == 1
    my buggy code // three
    post neibor, degree == 1
    post neibor, degree == 2
    post neibor, degree == 3
    end
    ==================
    head
    pre neibor, degree == 2
    pre neibor, degree == 1
    my buggy code // four
    post neibor, degree == 1
    post neibor, degree == 2
    end
    ==================
    '''

    patched = patching(patch, raw_code_lines=raw_code.splitlines())
    print("@@@@@@@@@@@")
    print(patched)


