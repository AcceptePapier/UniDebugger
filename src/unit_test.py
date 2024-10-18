import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import json_pretty_dump, read_json, return_lines
from src.prompts.prepare import get_info_dict

def test_helper(info):
    from src.agents.helper import Helper
    helper = Helper("gpt-4o-2024-08-06", hash_id="unittest")
    response = helper.run(info)
    if not os.path.exists("../unit/ori_resp/helper.txt"):
        with open("../unit/ori_resp/helper.txt", "w") as wf:
            wf.write(response["ori"])
    else:
        with open("../unit/ori_resp/helper.txt") as rf: 
            response = helper.parse_response(rf.read())
    
    print(response["aim"])
    print("<"*50)
    print(response["exp"])
    with open("../unit/aim_save/helper.txt", "w") as wf:
        wf.write(response["aim"])

def test_repofocus(model_name, info):
    from src.agents.repofocus import RepoFocus
    repofocus = RepoFocus(model_name, hash_id="unittest")
    if not os.path.exists("../unit/ori_resp/repofocus.txt"):
        response = repofocus.run(info)
        with open("../unit/ori_resp/repofocus.txt", "w") as wf:
            wf.write(response["ori"])
    else:
        with open("../unit/ori_resp/repofocus.txt") as rf: 
            response = repofocus.parse_response(rf.read(), 
                                                project_src_path=info["project_meta"]["project_src_path"])
    
    print(response["aim"])
    print("<"*50)
    print(response["exp"])
    with open("../unit/aim_save/repofocus.txt", "w") as wf:
        wf.write("\n".join(response["aim"]))

def test_summarizer(model_name):
    bug_related_lst = return_lines("../unit/aim_save/repofocus.txt")

    from src.agents.summarizer import Summarizer
    summarizer = Summarizer(model_name, hash_id="unittest")
    
    import json
    if not os.path.exists("../unit/ori_resp/summarizer.txt"):
        summary = {}
        for file in bug_related_lst:
            if not file.endswith("java"): continue
            if os.path.exists(os.path.join(info["project_meta"]["project_src_path"], file)):
                with open(os.path.join(info["project_meta"]["project_src_path"], file)) as rf:
                    code = rf.read()
            response = summarizer.run(code)
            summary.update({file: response["aim"]})
        
        with open("../unit/ori_resp/summarizer.txt", "w") as wf:
            wf.write(json.dumps(summary))
    else:
        with open("../unit/ori_resp/summarizer.txt") as rf:
            summary = summarizer.parse_response(response=rf.read())["aim"]
    
    json_pretty_dump(summary, "../unit/aim_save/summarizer.json")

def test_slicer(model_name, info):

    from src.agents.slicer import Slicer
    slicer = Slicer(model_name, hash_id="unittest")
    
    if not os.path.exists("../unit/ori_resp/slicer.txt"):
        pre_agent_resp = {}
        if os.path.exists("../unit/aim_save/helper.txt"):
            with open("../unit/aim_save/helper.txt") as rf:
                pre_agent_resp["helper"] = rf.read()
        if os.path.exists("../unit/aim_save/summarizer.json"):
            pre_agent_resp["summarizer"] = json.dumps(read_json("../unit/aim_save/summarizer.json"))

        response = slicer.run(info, pre_agent_resp)
        with open("../unit/ori_resp/slicer.txt", "w") as wf:
            wf.write(response["ori"])
    else:
        with open("../unit/ori_resp/slicer.txt") as rf: 
            response = slicer.parse_response(rf.read(), raw_code=info["buggy_code"])
    
    print(response["aim"])
    print("<"*50)
    print(response["exp"])
    
    with open("../unit/aim_save/slicer.java", "w") as wf:
        wf.write(response["aim"])

def test_locator(model_name, info):
    from src.agents.locator import Locator
    locator = Locator(model_name=model_name, hash_id="unittest")
    pre_agent_resp = {}
    if os.path.exists("../unit/aim_save/slicer.txt"):
        with open("../unit/aim_save/slicer.txt") as rf:
            pre_agent_resp["slicer"] = rf.read()
    raw_code = pre_agent_resp["slicer"] if "slicer" in pre_agent_resp else info["buggy_code"]

    if not os.path.exists("../unit/ori_res/locator.txt"):
        if os.path.exists("../unit/aim_save/helper.txt"):
            with open("../unit/aim_save/helper.txt") as rf:
                pre_agent_resp["helper"] = rf.read()
        if os.path.exists("../unit/aim_save/summarizer.json"):
            pre_agent_resp["summarizer"] = json.dumps(read_json("../unit/aim_save/summarizer.json"))
        
        response = locator.run(info, pre_agent_resp)
        with open("../unit/ori_resp/locator.txt", "w") as wf:
            wf.write(response["ori"])
    else:
        with open("../unit/ori_resp/locator.txt") as rf: 
            response = locator.parse_response(rf.read(), raw_code=raw_code)
    
    print(response["aim"])
    print("<"*50)
    print(response["exp"])
    with open("../unit/aim_save/locator.java", "w") as wf:
        wf.write(response["aim"])

def test_fixer(model_name, info):
    from agents.fixer import Fixer
    fixer = Fixer(model_name=model_name, hash_id="unittest")

    if not os.path.exists("../unit/ori_res/fixer.txt"):
        pre_agent_resp = {}
        if os.path.exists("../unit/aim_save/locator.txt"):
            with open("../unit/aim_save/locator.txt") as rf:
                pre_agent_resp["locator"] = rf.read()
        if os.path.exists("../unit/aim_save/helper.txt"):
            with open("../unit/aim_save/helper.txt") as rf:
                pre_agent_resp["helper"] = rf.read()
        if os.path.exists("../unit/aim_save/summarizer.json"):
            pre_agent_resp["summarizer"] = json.dumps(read_json("../unit/aim_save/summarizer.json"))
        

        response = fixer.run(info, pre_agent_resp)
        with open("../unit/ori_resp/fixer.txt", "w") as wf:
            wf.write(response["ori"])
    else:
        with open("../unit/ori_resp/fixer.txt") as rf: 
            response = fixer.parse_response(rf.read(), raw_code=info["buggy_code"])
    
    print(response["aim"])
    print("<"*50)
    print(response["exp"])
    with open("../unit/aim_save/fixer.patch", "w") as wf:
        wf.write(response["aim"])

def test_fixerpro(model_name, info, container_id):
    from src.agents.fixerpro import FixerPro

    with open("../unit/aim_save/fixer.patch") as rf:
        patch = rf.read()
    info["project_meta"]["checkout_dir"] = "checkouts"
    info["project_meta"]["buggy_file_path"] = "checkouts/Lang_1_buggy/src/main/java/org/apache/commons/lang3/math/NumberUtils.java"
    fixerpro = FixerPro(model_name=model_name, hash_id="unittest")
    
    from src.patch import patching_and_testing
    plausible = patching_and_testing(patch, info["project_meta"], container_id)
    print(f"The patch is {plausible}")
    
    if not os.path.exists("../unit/ori_res/fixerpro.txt"):
        pre_agent_resp = {}
        if os.path.exists("../unit/aim_save/helper.txt"):
            with open("../unit/aim_save/helper.txt") as rf:
                pre_agent_resp["helper"] = rf.read()
        if os.path.exists("../unit/aim_save/summarizer.json"):
            pre_agent_resp["summarizer"] = json.dumps(read_json("../unit/aim_save/summarizer.json"))
        response = fixerpro.run(info, plausible, patch, pre_agent_resp)
        with open("../unit/ori_resp/fixerpro.txt", "w") as wf:
            wf.write(response["ori"])
    else:
        with open("../unit/ori_resp/fixerpro.txt") as rf: 
            response = fixerpro.parse_response(rf.read(), raw_code=info["buggy_code"])
    
    print(response["aim"])
    print("<"*50)
    print(response["exp"])
    with open("../unit/aim_save/fixerpro.patch", "w") as wf:
        wf.write(response["aim"])
    

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--test", default="slicer", type=str)
params = vars(parser.parse_args())

if __name__ == "__main__":
    model_name = "gpt-3.5-turbo-ca"
    container_id = '7bdc33a65712'
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s P%(process)d %(levelname)s %(message)s",
        handlers=[logging.FileHandler(f"../unit/{params['test']}.log"), logging.StreamHandler()],
    )
    info = get_info_dict(checkout_dir="../unit/cases", 
                         bug_name="Lang_1", 
                         model_name=model_name, 
                         root_causes={"Lang_1": "src/main/java/org/apache/commons/lang3/math/NumberUtils.java"}
    )
    os.makedirs("../unit/ori_resp", exist_ok=True)
    os.makedirs("../unit/aim_save", exist_ok=True)

    if params["test"] == "helper": test_helper(info)
    if params["test"] == "repofocus": test_repofocus(model_name, info)
    if params["test"] == "summarizer": test_summarizer(model_name)
    if params["test"] == "slicer": test_slicer(model_name, info)
    if params["test"] == "locator": test_locator(model_name, info)
    if params["test"] == "fixer": test_fixer(model_name, info)
    if params["test"] == "fixerpro": test_fixerpro(model_name, info, container_id)



    