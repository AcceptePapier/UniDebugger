import logging
import json
from utils import temporary_save, read_yaml, read_json
from parse import *
from agents.agent import Agent
from agents.fixer import Fixer
from patch import patching_and_testing
from prompts.tokens import *
import os

class FixerPro(Agent):
    def parse_response(self, response: str):
        patch = parse_code(response)[0].strip()
        if "===" in patch:
            patch = patch[:patch.find("===")].strip()
        return {"aim": patch, "exp": parse_exp(response), "ori": response}
    
    def __generate_core_msg(self, info, pre_agent_resp, plau_label_prompt):
        if "locator" in pre_agent_resp:
            logging.info("Fix code with marks of buggy lines")
            self.core_msg = "The following code contains a bug with suspious lines labeled:\n" + pre_agent_resp["locator"]
        else:
            self.core_msg = "The following code contains a bug:\n" + info["buggy_code"]

        self.__shared_msg(info, pre_agent_resp)
        if "coverage_report" in info and calculate_token(self.core_msg + info["coverage_report"]) <= token_limit[self.model_name]["overall"]:
            self.core_msg = "Code coverage for failed testcases:\n" + info["coverage_report"] + "\n" + self.core_msg
        logging.info(f"Current core message tokens: {calculate_token(self.core_msg)}")

    def run(self, 
            info: dict, 
            plausible, 
            patch,
            pre_agent_resp: dict={}, 
            *args
        ):
        logging.info("## Running FixerPro...")
        self.prompts_dict = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/fixerpro.yaml"))
        
        plau_label = "plausible" if plausible else "not plausible"
        if self.core_msg is None:
            self.__generate_core_msg(info, pre_agent_resp, f"A generated patch that is {plau_label}:\n" + patch)
        
        return self.parse_response(self.send_message([
                    {"role": "system", "content": self.prompts_dict["sys"][plau_label]},
                    {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"][plau_label]}]   
            )
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

            
    

        
    



