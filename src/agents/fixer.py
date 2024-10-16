import os
from retry import retry
from utils import read_yaml
from parse import *
from prompts.tokens import *
from agents.agent import Agent

class Fixer(Agent):
    def parse_response(self, response: str):
        patch = parse_code(response)[0].strip()
        if "===" in patch:
            patch = patch[:patch.find("===")].strip()
        return {"aim": patch, "exp": parse_exp(response), "ori": response}
        
    def __generate_core_msg(self, info, pre_agent_resp):
        if "locator" in pre_agent_resp:
            logging.info("Fix code with marks of buggy lines")
            self.core_msg = "The following code contains a bug with suspious lines labeled:\n" + pre_agent_resp["locator"]
        else:
            self.core_msg = "The following code contains a bug:\n" + info["buggy_code"]
            
        self.__shared_msg(info, pre_agent_resp)
        if "coverage_report" in info and calculate_token(self.core_msg + info["coverage_report"]) <= token_limit[self.model_name]["overall"]:
            self.core_msg = "Code coverage for failed testcases:\n" + info["coverage_report"] + "\n" + self.core_msg
        
        logging.info(f"Current core message tokens: {calculate_token(self.core_msg)}")

    @retry((NoCodeError), tries=3, delay=5)
    def run(self, info: dict, pre_agent_resp: dict={}, *args):
        logging.info("## Running Fixer...")
        self.label_key = "labeled" if "locator" in pre_agent_resp else "unlabeled"
        self.prompts_dict = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/fixer.yaml"))
        if self.core_msg is None:
            self.__generate_core_msg(info, pre_agent_resp)

        return self.parse_response(self.send_message([
                    {"role": "system", "content": self.prompts_dict["sys"][self.label_key]},
                    {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]}])
        )
    
    def refine(self, assist_resp, test_res, *args):
        refine_prompt = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/refine.yaml"))
        return self.parse_response(self.send_message([
                    {"role": "system", "content": self.prompts_dict["sys"][self.label_key]},
                    {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]},
                    {"role": "assistant", "content": assist_resp},
                    {"role": "user", "content": "\nYour generated patch fails because:\n" + test_res + refine_prompt["fixer"]}
                ]
            )
        )
    
        
    



