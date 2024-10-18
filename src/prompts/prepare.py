import os
from utils import *
from prompts.tokens import *

'''
The info contains the most necessary information for a bug (called bug metadata)
project_meta:
- project_name: The original project name, consistent with that in the d4j repo.
- project_src_path: The location of the source code in the project, usually in the src/source folder.
- buggy_number: The buggy number, consistent with that in the d4j repo.
- bug_name: project_name{_}buggy_number.
- checkout_dir: The folder used for checkouts by defects4j.
buggy_file_path: The file path where the bug is located, extracted according to the failing_info information.
failing_test_cases: Test code that triggers the bug.
buggy_code: The file content of buggy_file_path.
packages: The content starting with import or packages in the buggy code. 
'''
def exist_java(dir_path):
    for file in os.listdir(dir_path):
        if file.endswith(".java"):
            return True
        
# import javalang
# def get_func_code_in_test(test_path, func):
#     with open(test_path) as tf:
#         test_code = tf.read()
#     print(test_code)
#     func_code = ""

#     if func in test_code:
#         tree = javalang.parse.parse(test_code)
#         for _, node in tree.filter(javalang.tree.MethodDeclaration):
#             if node.name == tree:
#                 logging.info("Test case found")
#                 func_code = test_code[node.position.line - 1:node.body.position.line - 1]
#         if len(func_code) == 0:
#             match = re.search(rf'(?s)(public\s+.*?\s+{func}\s*\([^)]*\)\s*\{{.*?\}})', test_code)
#             if match:
#                 func_code = match.group(1) 
#         if len(func_code) == 0:
#             logging.warning(f"Cannot find {func} in {test_path}!")
#     else:
#         logging.warning(f"{func} is not in {test_path}")
    
#     return func_code


def get_failing_info(project_dir, model_name):
    
    for test_file in ["tests", "test", "src/test/org", "src/test/java", "gson/src/test/java"]:
        if os.path.exists(f"{project_dir}/{test_file}"):
            test_file_path = test_file if test_file != "src/test/org" else "src/test"

    assert os.path.exists(os.path.join(project_dir, test_file_path)), "\n".join(os.listdir(project_dir))
    failing_test_cases = ""
    testing_error = ""
    with open(os.path.join(project_dir, "failing_tests")) as rf:
        failing_info = rf.read().splitlines()

    ori_path, test_code = None, None
    testing_error = ""
    for l in failing_info:
        if l.startswith("--- "):
            ori_path, func = l.replace("--- ", "").split("::")
            path = os.sep.join(ori_path.split(".")) + ".java"
            if os.path.exists(os.path.join(project_dir, test_file_path, path)):
                with open(os.path.join(project_dir, test_file_path, path)) as rf:
                    test_code = rf.read().splitlines()
        
        if not l.strip().startswith("at "):
            testing_error += l + "\n"
        elif ori_path is not None and test_code is not None and (ori_path+"."+func).strip() in l:
            line_idx = int(l.split(":")[-1].strip().strip(")")) - 1
            i = line_idx - 1
            while i >= 0:
                if "assert" in test_code[i] or "public" in test_code[i] or "private" in test_code[i]:
                    break    
                i -= 1
            test_code[line_idx] += "\n/*\n" + testing_error + "*/"
            testing_error = ""
            failing_test_cases += f"public void {func}" + "{\n" + "\n".join([c for c in test_code[i + 1: line_idx + 1] if len(c.strip()) > 0]) + "\n}"

    return failing_test_cases

def print_info_tokens(info):
    print("Tokens of info:")
    for k, v in info.items():
        if k in ["failing_test_cases", "buggy_code", "packages", "coverage_report"]:
            print(k, ">>>", calculate_token(v))
    print(info["failing_test_cases"])
    print()

def get_info_dict(checkout_dir: str, bug_name: str, model_name: str, root_causes: dict=None):
    [project_name, buggy_number] = bug_name.split("_")
    info = {
        "project_meta": {
            "project_name": project_name,
            "buggy_number": buggy_number,
            "checkout_dir": checkout_dir,
            "bug_name": bug_name
        },
    }
    if root_causes is None:
        root_causes = read_json(os.path.join(checkout_dir, "root_cause_path.json"))

    project_dir = os.path.join(checkout_dir, f"{bug_name}_buggy") 
    info["project_meta"]["buggy_file_path"] = os.path.join(project_dir, root_causes[bug_name])
    
    src_path_split = root_causes[bug_name].split(os.sep)
    for e in range(1, len(root_causes[bug_name].split(os.sep))+1):
        src_dir = os.sep.join([project_dir] + src_path_split[:e])
        if exist_java(src_dir):
            info["project_meta"]["project_src_path"] = src_dir
            break

    with open(info["project_meta"]["buggy_file_path"]) as rf:
        info["raw_code"] = rf.read()
    
    if os.path.exists(os.path.join(project_dir, "coverage_report.txt")):
        with open(os.path.join(project_dir, "coverage_report.txt")) as rf:
            info["coverage_report"] = rf.read()
    
    info["buggy_code"] = shorten(info["raw_code"], token_limit[model_name]["buggy_code"], 
                                 return_lines(os.path.join(project_dir, "coverage_indices.txt"))
    )
    
    info["packages"] = "\n".join([l for l in info["raw_code"].splitlines() 
                                if l.strip().startswith("import") or l.strip().startswith("package")])
    
    info["failing_test_cases"] = get_failing_info(project_dir, model_name)
    
    print_info_tokens(info)
    return info
     


