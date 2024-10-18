import logging
import os
from retry import retry
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.agent import Agent, RetryError
from prompts.tokens import *
from utils import read_yaml
from parse import *

  
class Locator(Agent):

    def parse_response(self, response: str, raw_code: str, comment_label="//"):
        # Extract code from agent's response
        resp_code = "\n".join([p.strip() for p in parse_code(response) if len(p.strip()) > 0])
        if "===" in resp_code:
            resp_code = resp_code[:resp_code.find("===")].strip()
        resp_lines, raw_code_lines = resp_code.splitlines(), raw_code.splitlines()
        raw_lines_w_marks = [l for l in raw_code_lines] # return
        
        mark_indces = {i: (-1, "") for i, l in enumerate(resp_lines) if "missing" in l or "buggy" in l}  # record the index of marked line
        for i, l in enumerate(resp_lines):
            if i not in mark_indces and i - 1 in mark_indces and not exist_line(l, raw_code_lines):
                mark_indces[i] = (-2, "")
        if len(mark_indces) == 0:
            raise RetryError("No mark in the response!")
        
        for resp_idx in sorted(list(mark_indces.keys())):
            if mark_indces[resp_idx][0] == -2 and resp_idx - 1 in mark_indces and mark_indces[resp_idx - 1][0] >= 0:
                mark_indces[resp_idx] = mark_indces[resp_idx - 1]
                (unique_idx, mode) = mark_indces[resp_idx - 1]
                if mode == "pre":
                    raw_lines_w_marks[unique_idx] += f"\n/* missing code:[{resp_lines[resp_idx].rstrip()}] */"
                else:
                    this_lines = raw_lines_w_marks[unique_idx].split("\n")
                    added, ori = "\n".join(this_lines[:-1]), this_lines[-1]
                    raw_lines_w_marks[unique_idx] = added + f"\n/* missing code:[{resp_lines[resp_idx]}] */\n" + ori
                    print("===\n", added + f"\n/* missing code:[{resp_lines[resp_idx]}] */\n" + ori, "\n===")
                continue

            code, comment = resp_lines[resp_idx].split(comment_label)[0].rstrip(), comment_label.join(resp_lines[resp_idx].split(comment_label)[1:]).strip()
            
            unique_idx = unique_matching(resp_lines, raw_code_lines, resp_idx)
            if unique_idx >= 0:
                raw_lines_w_marks[unique_idx] += " // " + comment
                mark_indces[resp_idx] = (unique_idx, "pre")
                continue
            elif unique_idx == -2 and (len(code) or "missing" in resp_lines[resp_idx]) > 0: # This line should be added, not modified
                print("\n--> Add this", resp_lines[resp_idx], "\n")
                pre_valid = search_valid_line(resp_lines, resp_idx, "pre", existing=raw_code_lines)
                if pre_valid is not None:
                    unique_idx = unique_matching(resp_lines, raw_code_lines, pre_valid[0], existing=True)
                    if unique_idx >= 0:
                        raw_lines_w_marks[unique_idx] += (f"\n/* missing code:[{code}] // {comment} */")
                        mark_indces[resp_idx] = (unique_idx, "pre")
                        continue
                post_valid = search_valid_line(resp_lines, resp_idx, "post", existing=raw_code_lines)
                if post_valid is not None:
                    unique_idx = unique_matching(resp_lines, raw_code_lines, post_valid[0], existing=True)
                    if unique_idx >= 0:
                        raw_lines_w_marks[unique_idx] = (f"/* missing code:[{code}] // {comment} */\n") + raw_lines_w_marks[unique_idx]
                        mark_indces[resp_idx] = (unique_idx, "post")         
        
        if sum(list([i[0]>=0 for i in mark_indces.values()])) == 0:
            raise RetryError(f"Cannot mark any line with {len(mark_indces)} marks")
        
        if sum(list([i[0]>=0 for i in mark_indces.values()])) < len(mark_indces): 
            for mark_idx in mark_indces:
                if not mark_indces[mark_idx]:
                    resp_lines[mark_idx] += "  // Cannot Mark!"
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

if __name__ == "__main__":
    locator = Locator(model_name="gpt_4o", hash_id="temporal", config_path="/Users/cheryl/Desktop/src/config.json")
    response = '''
    ```
    add_0 // missing code
    add_1 
    add_2
    add_3
    post neibor, degree == 1
    post neibor, degree == 2
    post neibor, degree == 3
    post neibor, degree == 4
    post neibor, degree == 5
    end
    ```
    ===
    explain
    ===
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
    head
    pre neibor, degree == 1
    my buggy code // five
    post neibor, degree == 1
    end
    ==================
    head
    my buggy code // six
    end
    '''

    result = locator.parse_response(response, raw_code)["aim"]
    print(result)
