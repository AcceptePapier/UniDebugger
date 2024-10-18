import os
from retry import retry
from parse import parse_code, parse_exp

from utils import read_yaml
from agents.agent import Agent, RetryError
from prompts.tokens import *
import subprocess


class RepoFocus(Agent):
    def parse_response(self, response: str, project_src_path: str):
        files = "\n".join([p.strip() for p in parse_code(response) if len(p.strip()) > 0])
        if "===" in files:
            files = files[:files.find("===")].strip()
        valid_files = [f for f in files.splitlines() 
                       if os.path.exists(os.path.join(project_src_path, f)) and "Test" not in f]
        if len(valid_files) == 0:
           raise RetryError(f"No valid files {files}")
        elif len(valid_files) > 5:
            valid_files = valid_files[:5]
            logging.warning("Too many valid files:\n" + '\n'.join(valid_files))
        return {"aim": valid_files, "exp": parse_exp(response), "ori": response}

    def __generate_core_msg(self, info):
        structure = subprocess.run(["tree"], cwd=info["project_meta"]["project_src_path"], capture_output=True, text=True).stdout

        self.core_msg = "Imported packages in the bug-located code file:\n" + info["packages"] + \
                        "\nThe code fails on this test:\n" + info["failing_test_cases"] + \
                        "\nStructrue of source code directory:\n" + structure

        if "coverage_report" in info and calculate_token(self.core_msg + info["coverage_report"]) <= token_limit[self.model_name]["overall"]:
            self.core_msg = "Code coverage for failed testcases:\n" + info["coverage_report"] + "\n" + self.core_msg


    @retry((RetryError), tries=3, delay=5)
    def run(self, info: dict, *args):
        logging.info("## Running RepoFocus...")
        self.prompts_dict = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/repofocus.yaml"))
        if self.core_msg is None:
            self.__generate_core_msg(info)
        
        return self.parse_response(
            self.send_message([
                    {"role": "system", "content": self.prompts_dict["sys"]},
                    {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]}
                ]
            ),
            info["project_meta"]["project_src_path"]
        )
