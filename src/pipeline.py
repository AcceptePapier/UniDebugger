import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.agents.fixer import Fixer
from src.agents.locator import Locator
from src.agents.slicer import Slicer
from src.agents.summarizer import Summarizer
from src.agents.fixerpro import FixerPro
from src.agents.repofocus import RepoFocus
from src.agents.helper import Helper
from src.prompts.prepare import get_info_dict
from src.prompts.tokens import *
from src.patch import patching_and_testing
from src.utils import *




import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--limit", default=1, type=int)
parser.add_argument("--model_name", default="gpt-3.5-turbo-ca", choices=list(token_limit.keys()))
parser.add_argument("--data_name", default="d4j")
parser.add_argument("--level", default=3, type=int)
parser.add_argument("--container_id", default='7bdc33a65712', type=str)
parser.add_argument("--re_patch_num", default=2, type=int)
parser.add_argument("--refinement", action="store_true")

params = vars(parser.parse_args())

role_dict = {"repofocus": RepoFocus, "locator": Locator, "fixer": Fixer, "slicer": Slicer, "summarizer": Summarizer, "fixerpro": FixerPro, "helper": Helper}
suffix_dict = {"repofocus": "json", "locator": "java", "fixer": "patch", "slicer": "java", "summarizer": "json", "fixerpro": "patch", "helper": "txt"}
level_dict = {1: ["locator", "fixer"], 2: ["summarizer", "slicer", "locator", "fixer"], 3: ["helper", "repofocus", "summarizer", "slicer", "locator", "fixer", "fixerpro"]}

class Pipeline():
    def __init__(self, 
                 model_name: str,
                 container_id,
                 data_name,
                 refinement=False,
                 level=3,
                 **kwargs):
        
        self.model_name = model_name
        self.container_id = container_id
        self.data_name = data_name
        self.level = level
        self.refinement = refinement
        self.record_dir, self.hash_id = dump_exp(f"../res/{data_name}/records", 
                                                 {"model_name": model_name, "level": level}
                                        )
        self.framework = {role: role_dict[role](model_name, self.hash_id) for role in level_dict[level]}
        self.response_dir = os.path.join(f"../res/{data_name}/resp", self.hash_id)
        os.makedirs(os.path.join(self.record_dir), exist_ok=True)
        self.records = {
                        "worked": return_lines(os.path.join(self.record_dir, "worked.txt")),
                        "failed": return_lines(os.path.join(self.record_dir, "failed.txt")),
                        "plausible": return_lines(os.path.join(self.record_dir, "plausible.txt")),
                        "implausi": return_lines(os.path.join(self.record_dir, "implausi.txt")),
        } 

        self.messages = {}
        self.agent_resp = {}
    
    def repair_with_fl(self, info, fl_path: str, re_patch_num=3): #ablation study only
        if os.path.exists(fl_path):
            assert fl_path.endswith(".java")
            with open(fl_path) as rf:
                fix_pre_resp = {"locator": rf.read()}
        for c in range(re_patch_num):
            print()
            logging.info(f"Generating the {c+1}-th patch")
            fix_response = self.framework["fixer"].run(info, fix_pre_resp)
            try:
                if patching_and_testing(patch=fix_response["aim"], project_meta=info["project_meta"]): #fixer生成了正确的patch
                    self.save(role="fixer", response_dict=fix_response, bug_name=info['project_meta']['bug_name'])
                    return True, fix_response["aim"]
            except Exception as e:
                temporary_save(fix_response, info["project_meta"])
                logging.error(f"Cannot test the generated patch because:\n{e}")
                raise Exception
        self.save(role="fixer", response_dict=fix_response, bug_name=info['project_meta']['bug_name'])
        return False, fix_response["aim"]

    
    def level_1_repair(self, info: dict, re_patch_num=3): 
        ##### Localize
        loc_response = self.framework["locator"].run(info, self.agent_resp)
        self.save(role="locator", response_dict=loc_response, bug_name=info['project_meta']['bug_name'])

        ##### Fix        
        for c in range(re_patch_num):
            print()
            logging.info(f"Generating the {c+1}-th patch")
            fix_response = self.framework["fixer"].run(info, self.agent_resp)
            self.save(role="fixer", response_dict=fix_response, bug_name=info['project_meta']['bug_name'])

            if patching_and_testing(patch=fix_response["aim"], project_meta=info["project_meta"]): 
                return True, fix_response["aim"]

        return False, fix_response["aim"]
    
    def level_2_repair(self, info: dict, re_patch_num=3):
        if "summarizer" not in self.agent_resp:
            ##### Summerize bug-located file
            sum_response = self.framework["summarizer"].run(info["buggy_code"])
            self.save(role="summarizer", response_dict=sum_response, bug_name=info['project_meta']['bug_name'])
        
        ##### Slice suspious snippet
        sli_response = self.framework["slicer"].run(info)
        self.save(role="slicer", response_dict=sli_response, bug_name=info['project_meta']['bug_name'])

        ##### Locate & Fix
        plausible, patch = self.level_1_repair(info, re_patch_num)
        
        ##### Further analyze the bug and fix
        ins_response = self.framework["fixerpro"].run(info, plausible, patch, self.agent_resp)
        self.save(role="fixerpro", response_dict=ins_response, bug_name=info['project_meta']['bug_name'])

        if not plausible: 
            plausible = patching_and_testing(patch=ins_response["aim"], project_meta=info["project_meta"])
            return plausible, ins_response["aim"]
        else:
            return True, patch
    
    def level_3_repair(self, info: dict, re_patch_num=3):
        ##### Identify a list of suspious files
        det_response = self.framework["repofocus"].run(info)
        self.save(role="repofocus", response_dict=det_response, bug_name=info['project_meta']['bug_name'])
        aim_file_lst = []
        for file in det_response["aim"]:
            if not file.endswith("java"): continue
            if os.path.exists(os.path.join(info["project_meta"]["project_src_path"], file)): aim_file_lst.append(file)
            else: logging.warning(f"Not exist: {os.path.join(info['project_meta']['project_src_path'], file)}")
        logging.info(f"There are {len(aim_file_lst)} code files need to be summerized")

        ##### Search for references
        hel_response = self.framework["helper"].run(info)
        self.save(role="helper", response_dict=hel_response, bug_name=info['project_meta']['bug_name'])

        ##### Summerize multiple files
        if "summarizer" in self.agent_resp:
            summary = {"root": json.dumps(self.agent_resp["summarizer"])}
        else:
            sum_response = self.framework["summarizer"].run(info["buggy_code"])
            self.save(role="summarizer", response_dict=sum_response, bug_name=info['project_meta']['bug_name'])
            summary = {"root": sum_response["aim"]}
        
        if calculate_token(json.dumps(summary)) < token_limit[self.model_name]["summary"]:
            logging.info(f"## Running Summarizer on multiple files...")
            for file in list(set(aim_file_lst)):
                if os.path.join(info["project_meta"]["project_src_path"], file) == info["project_meta"]["buggy_file_path"]: continue
                logging.info(f"* {file}")
                
                with open(os.path.join(info["project_meta"]["project_src_path"], file)) as rf:
                    code = shorten(rf.read(), token_limit[self.model_name]["buggy_code"])
                if calculate_token(code) >= token_limit[self.model_name]["buggy_code"]:
                    logging.warning(f"Too long code file: {file}")
                    continue

                sum_response = self.framework["summarizer"].run(code)
                if calculate_token(json.dumps(summary)) + calculate_token(json.dumps(sum_response["aim"])) >= token_limit[self.model_name]["summary"]:
                    break
                summary.update({file: sum_response["aim"]})
                
        self.save(role="summarizer", 
                  response_dict={"ori": json.dumps(summary), "aim": summary, "exp": ""}, 
                  bug_name=info['project_meta']['bug_name']
        )
        
        return self.level_2_repair(info, re_patch_num=re_patch_num)
        
        
    def refine(self, info, patch_test_res):
        # Fixerpro refine
        logging.info("FixerPro self-refining...")
        ins_response = self.framework["fixerpro"].refine(self.messages["fixerpro"], patch_test_res)
        if patching_and_testing(patch=ins_response["aim"], project_meta=info["project_meta"]):
            self.save(role="fixerpro", response_dict=ins_response, bug_name=info['project_meta']['bug_name'])
            return True, ins_response["aim"]
        
        # Fixer refine
        logging.info("Fixer self-refining...")
        fix_response = self.framework["fixer"].refine(self.messages["fixer"], patch_test_res)
        plausible = patching_and_testing(patch=fix_response["aim"], project_meta=info["project_meta"])
        if plausible:
            self.save(role="fixer", response_dict=fix_response, bug_name=info['project_meta']['bug_name'])
        logging.info("> FixerPro self-refining...")
        ins_response = self.framework["fixerpro"].run(info, plausible, fix_response["aim"], self.agent_resp)
        if patching_and_testing(patch=ins_response["aim"], project_meta=info["project_meta"]):
            self.save(role="fixerpro", response_dict=ins_response, bug_name=info['project_meta']['bug_name'])
            return True, ins_response["aim"]
        
        # Locator refine
        logging.info("Locator self-refining...")
        loc_response = self.framework["locator"].refine(self.messages["locator"])
        self.save(role="locator", response_dict=loc_response, bug_name=info['project_meta']['bug_name'])
        logging.info("> Fixer self-refining...")
        fix_response = self.framework["fixer"].refine(self.messages["fixer"], patch_test_res)
        plausible = patching_and_testing(patch=fix_response["aim"], project_meta=info["project_meta"])
        if plausible:
            self.save(role="fixer", response_dict=fix_response, bug_name=info['project_meta']['bug_name'])
        logging.info(">> FixerPro self-refining...")
        ins_response = self.framework["fixerpro"].run(info, plausible, fix_response["aim"], self.agent_resp)
        if patching_and_testing(patch=ins_response["aim"], project_meta=info["project_meta"]):
            self.save(role="fixerpro", response_dict=ins_response, bug_name=info['project_meta']['bug_name'])
            return True, ins_response["aim"]
        
        # Slicer refine
        logging.info("Slicer self-refining...")
        sli_response = self.framework["slicer"].refine(self.messages["slicer"])
        self.save(role="slicer", response_dict=sli_response, bug_name=info['project_meta']['bug_name'])
        logging.info("> Locator self-refining...")
        loc_response = self.framework["locator"].refine(self.messages["locator"])
        self.save(role="locator", response_dict=loc_response, bug_name=info['project_meta']['bug_name'])
        logging.info(">> Fixer self-refining...")
        fix_response = self.framework["fixer"].refine(self.messages["fixer"], patch_test_res)
        plausible = patching_and_testing(patch=fix_response["aim"], project_meta=info["project_meta"])
        if plausible:
            self.save(role="fixer", response_dict=fix_response, bug_name=info['project_meta']['bug_name'])
        logging.info(">>> FixerPro self-refining...")
        ins_response = self.framework["fixerpro"].run(info, plausible, fix_response["aim"], self.agent_resp)
        if patching_and_testing(patch=ins_response["aim"], project_meta=info["project_meta"]):
            self.save(role="fixerpro", response_dict=ins_response, bug_name=info['project_meta']['bug_name'])
            return True, ins_response["aim"]
        
        return False, ins_response["aim"]
        

    def save(self, role: str, response_dict: dict, bug_name: str) -> bool:

        suffix = suffix_dict[role]
        os.makedirs(os.path.join(self.response_dir, role, f"aim"), exist_ok=True)
        os.makedirs(os.path.join(self.response_dir, role, f"exp"), exist_ok=True)
        os.makedirs(os.path.join(self.response_dir, role, f"ori"), exist_ok=True)

        if response_dict is None:
            write_line(os.path.join(self.record_dir, "failed_lst.txt"), bug_name)
            self.messages[role] = ""
            return False
                    
        for k, v in response_dict.items():
            if k == "aim":
                cur_s = suffix
                self.agent_resp[role] = json.dumps(response_dict["aim"]) if role == "summarizer" else response_dict["aim"]
            else:
                cur_s = "txt"
            if cur_s == "json":
                json_pretty_dump(v, os.path.join(self.response_dir, role, f"{k[:3]}", f"{bug_name}.{cur_s}"))
            else:
                with open(os.path.join(self.response_dir, role, f"{k[:3]}", f"{bug_name}.{cur_s}"), "w") as wf:
                    wf.write(v)
        
        self.messages[role] = response_dict["ori"]
            
    def looping(self, limit=-1, re_patch_num=3, **kwargs):
        root_casues = read_json(f"../benchmarks/{self.data_name}/root_cause_path.json")
        work_num, plau_num = len(self.records["worked"]), len(self.records["plausible"])
        cnt = work_num + len(self.records["failed"]) 
        
        for bug_name in sorted(list(root_casues.keys())):
            if limit > 0 and cnt >= limit: return work_num, plau_num
            if bug_name in self.records["failed"] + self.records["worked"]: continue
            logging.info(f"Running on {cnt+1}-th bug {bug_name} @{self.hash_id}")
            
            info = get_info_dict(
                os.path.abspath(f"../benchmarks/{self.data_name}/checkouts"), 
                bug_name=bug_name, 
                model_name=self.model_name,
                root_causes=root_casues,
            )
            print()
            logging.info("***** Level 1 repairing...")
            plausible, patch = self.level_1_repair(info=info, re_patch_num=re_patch_num)
            if plausible: write_line(os.path.join(self.record_dir, "plausible_level1.txt"), bug_name)
            plausible, patch = False, None
            if not plausible and self.level >= 2:
                print()
                logging.info("***** Level 2 repairing...")
                plausible, patch = self.level_2_repair(info=info, re_patch_num=re_patch_num)
                if plausible: write_line(os.path.join(self.record_dir, "plausible_level2.txt"), bug_name)
                if not plausible and self.level >= 3:
                    print()
                    logging.info("***** Level 3 repairing...")
                    plausible, patch = self.level_3_repair(info=info, re_patch_num=re_patch_num)
                if not plausible and self.refinement:
                    print()
                    logging.info("***** Refining...")
                    plausible, patch = self.refine(info=info)
            
            if patch is not None:
                write_line(os.path.join(self.record_dir, "worked.txt"), bug_name)
            else:
                write_line(os.path.join(self.record_dir, "failed.txt"), bug_name)
            
            if plausible:
                logging.info("$$ Get a plausible patch!")
                write_line(os.path.join(self.record_dir, "plausible.txt"), bug_name)
            else:
                write_line(os.path.join(self.record_dir, "implausi.txt"), bug_name)

            plau_num += plausible; work_num += (patch is not None)
            cnt += 1
            
        return work_num, plau_num

if __name__ == "__main__": 

    workpipe = Pipeline(**params)
    work_num, plau_num = workpipe.looping(**params)
    
    logging.info(f"{workpipe.hash_id}@ In total, {work_num} patches are generated, {plau_num} of which are plausible!")
    

                




                





    
