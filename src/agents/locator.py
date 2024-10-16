import logging
import os
from retry import retry
from utils import read_yaml
from parse import *
from agents.agent import Agent, RetryError
from prompts.tokens import *
  
class Locator(Agent):

    def parse_response(self, response: str, raw_code: str):
        # Extract code from agent's response
        resp_code = "\n".join([p.strip() for p in parse_code(response) if len(p.strip()) > 0])
        if "===" in resp_code:
            resp_code = resp_code[:resp_code.find("===")].strip()
        resp_lines, raw_code_lines = resp_code.splitlines(), raw_code.splitlines()
        raw_lines_w_marks = [l for l in raw_code_lines] # return
        
        mark_indces = {i: False for i, l in enumerate(resp_lines) if "missing" in l or "buggy" in l}  # 记录missing or buggy 是否成功标记了
        if len(mark_indces) == 0:
            raise RetryError("No mark in the response!")
        
        for resp_idx in mark_indces:
            if mark_indces[resp_idx]: continue
            unique_idx = unique_matching(resp_lines, raw_code_lines, resp_idx)
            if unique_idx >= 0:
                raw_lines_w_marks[unique_idx] += "// " + resp_lines[resp_idx].split("//")[-1].strip()
                mark_indces[resp_idx] = True
                continue
            elif len(resp_lines[resp_idx].split("//")[0].strip()) > 0: # This line should be added, not modified
                [(_, pre_valid_idx)] = search_valid_line(resp_lines, resp_idx, "pre")
                pre_unique = unique_matching(resp_lines, raw_code_lines, pre_valid_idx)
                if pre_unique >= 0:
                    raw_lines_w_marks[pre_unique] += ("\n// " + resp_lines[resp_idx].rstrip())
                    mark_indces[resp_idx] = True
                    continue
                [(_, post_valid_idx)] = search_valid_line(resp_lines, resp_idx, "post")
                post_unique = unique_matching(resp_lines, raw_code_lines, post_valid_idx)
                if post_unique >= 0:
                    mark_indces[resp_idx] = True
                    comment = "/*\n"
                    for i in range(resp_idx, post_valid_idx):
                        comment += mark_indces[i]
                    comment += "*/\n" 
                    raw_lines_w_marks[post_unique] = comment + raw_lines_w_marks[post_unique]
        
        if sum(list(mark_indces.values())) == 0: #没有一行标记成功
            raise RetryError(f"Cannot mark any line with {len(mark_indces)} marks")
        
        if sum(list(mark_indces.values())) < len(mark_indces): #存在没能成功匹配上的行
            for mark_idx in mark_indces:
                if not mark_indces[mark_idx]:
                    resp_lines[mark_idx] += "  /* Cannot Mark!*/"
            logging.warning("Some labeled lines seem not from the original code")
            print("*"*30, "Cannot marked lines")
            print("\n".join(resp_lines))
            print("*"*30)

        return {"aim": "\n".join(raw_lines_w_marks), "exp": parse_exp(response), "ori": response}

    def __generate_core_msg(self, info, pre_agent_resp):
        if "slicer" in pre_agent_resp:
            logging.info("Mark buggy lines on suspicious code segment")
            self.core_msg = "The following code contains a bug:\n" + pre_agent_resp["slicer"]
        else:
            self.core_msg = "The following code contains a bug:\n" + info["buggy_code"]
        
        self.__shared_msg(info, pre_agent_resp)
        logging.info(f"Current core message tokens: {calculate_token(self.core_msg)}")

    def fast_parse(self, response):
        resp_code = "\n".join([p.strip() for p in parse_code(response) if len(p.strip()) > 0])
        if "===" in resp_code:
            resp_code = resp_code[:resp_code.find("===")].strip()
        return {"aim": resp_code, "exp": parse_exp(response), "ori": response}
    
    def run(self, info: dict, pre_agent_resp: dict={}, max_retries=5, *args):
        logging.info("## Running Locator...")
        self.prompts_dict = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/locator.yaml"))
        if self.core_msg is None:
            self.__generate_core_msg(info, pre_agent_resp)
        
        raw_code = pre_agent_resp["slicer"] if "slicer" in pre_agent_resp else info["buggy_code"]
        
        attempt = 0
        bk_resp = None
        
        while attempt < max_retries:
            try:
                if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../tools/coverage_report.txt")):
                    response = self.send_message([
                        {"role": "system", "content": self.prompts_dict["sys"]},
                        {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]}],
                        handling=False,
                        tools=[{"type": "function",
                            "function": {
                                "name": "failing_coverage",
                                "description": "Get code coverage for failed testcases.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {},
                                    "required": [],
                                }
                            }
                        }],   
                    )
                    if response.choices[0].finish_reason == "tool_calls":
                        if "coverage_report" in info:
                            context = info["coverage_report"]
                        else: 
                            context = "Coverage report it not available currently"
                        response = self.send_message([
                                {"role": "system", "content": self.prompts_dict["sys"]},
                                {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]},
                                response.choices[0].message,
                                {"role": "tool", "content": context, "tool_call_id": response.choices[0].message.tool_calls[0].id},
                            ]
                        )
                else:
                    if "coverage_report" in info and calculate_token(self.core_msg + info["coverage_report"]) <= token_limit[self.model_name]["overall"]:
                        self.core_msg = "Code coverage for failed testcases:\n" + info["coverage_report"] + "\n" + self.core_msg
                    response = self.send_message([
                        {"role": "system", "content": self.prompts_dict["sys"]},
                        {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]}],
                    )
                return self.parse_response(response, raw_code)
            except NoCodeError:
                attempt += 1
                logging.warning("No code, try again")
            except RetryError:
                attempt += 1
                mark = sum([("// buggy line" in l or "// missing" in l) for l in parse_code(response)])
                if mark > 0: bk_resp = response
                else:
                    logging.warning("Cannot mark any line, try again")
        
        if bk_resp is not None:
            return self.fast_parse(bk_resp)
        else:
            raise ValueError("No avaliable localization results!")
    
    def refine(self, assist_resp, *args):
        refine_prompt = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/refine.yaml"))
        return self.parse_response(self.send_message([
                    {"role": "system", "content": self.prompts_dict["sys"]},
                    {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]},
                    {"role": "assistant", "content": assist_resp},
                    {"role": "user", "content": "\nModifying your marked lines cannot fix the bug:\n" + refine_prompt["locator"]}
                ]
            )
        )
