import os
from retry import retry
import json
from utils import read_yaml,read_json
from parse import *
from agents.agent import Agent, RetryError
from prompts.tokens import *


class Slicer(Agent):
        
    def parse_response(self, response: str, raw_code: str):
        segment = "\n".join([p.strip() for p in parse_code(response) if len(p.strip()) > 0])
        if "===" in segment:
            segment = segment[:segment.find("===")].strip()
        
        seg_lines = segment.splitlines()
        raw_code_lines = raw_code.splitlines()
        seg_s, seg_e = -1, -1

        for start_idx in range(-1, len(seg_lines)-1): # search for a valid line in the beginning lines
            [(_, valid_idx)] = search_valid_line(seg_lines, start_idx, mode="post") 
            unique_idx = unique_matching(seg_lines, raw_code_lines, valid_idx)
            if unique_idx >= 0:
                seg_s = unique_idx
                break
        
        if seg_s == -1: 
            logging.warning("Cannot locate beginning line of the segment!")

        for end_idx in range(len(seg_lines), 1, -1):
            [(_, valid_idx)] = search_valid_line(seg_lines, end_idx, mode="pre") 
            unique_idx = unique_matching(seg_lines, raw_code_lines, valid_idx)
            if unique_idx >= 0:
                seg_e = unique_idx
                break
        if seg_s < 0 and seg_e < 0:
            raise RetryError("Cannot locate the suspious segment!\n"+segment)
        elif seg_s >= 0 and seg_e >= 0:
            real_seg = "\n".join(raw_code_lines[max(0, seg_s-10): min(len(raw_code_lines), seg_e+10)])
        else:
            if seg_e >= 0:
                real_seg_lines = []
                for i in range(min(len(raw_code_lines)-1, seg_e+10), -1, -1):
                    if len(real_seg_lines) >= 50: break
                    if not(raw_code_lines[i].strip().startswith('*') or raw_code_lines[i].strip().startswith('/*')):
                        real_seg_lines.append(raw_code_lines[i])
                real_seg = "\n".join(real_seg_lines[::-1])
            else:
                real_seg_lines = []
                for i in range(max(0, seg_s-10), seg_s+50):
                    if len(real_seg_lines) >= 50: break
                    if not(raw_code_lines[i].strip().startswith('*') or raw_code_lines[i].strip().startswith('/*')):
                        real_seg_lines.append(raw_code_lines[i])
                real_seg = "\n".join(real_seg_lines)
            
        return {"aim": real_seg, "exp": parse_exp(response), "ori": response}

    def __generate_core_msg(self, info, pre_agent_resp):
        self.core_msg = "The following code contains a bug:\n" + info["buggy_code"]
        self.__shared_msg(info, pre_agent_resp)
        if "coverage_report" in info and calculate_token(self.core_msg + info["coverage_report"]) <= token_limit[self.model_name]["overall"]:
            self.core_msg = "Code coverage for failed testcases:\n" + info["coverage_report"] + "\n" + self.core_msg

        logging.info(f"Current core message tokens: {calculate_token(self.core_msg)}")

    @retry((NoCodeError, RetryError), tries=3, delay=5)
    def run(self, info: dict, pre_agent_resp: dict={}):
        logging.info("## Running Slicer...")
        self.prompts_dict = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/slicer.yaml"))
        if self.core_msg is None:
            self.__generate_core_msg(info, pre_agent_resp)
       
        return self.parse_response(
            self.send_message([
                {"role": "system", "content": self.prompts_dict["sys"]},
                {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]}
            ]),
            raw_code=info["buggy_code"]
        )
    
    def refine(self, assist_resp, *args):
        refine_prompt = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/refine.yaml"))
        return self.parse_response(self.send_message([
                    {"role": "system", "content": self.prompts_dict["sys"]},
                    {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]},
                    {"role": "assistant", "content": assist_resp},
                    {"role": "user", "content": "\nModifying your isolated code segment cannot fix the bug:\n" + refine_prompt["slicer"]}
                ]
            )
        )