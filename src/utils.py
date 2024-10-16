import os
import json
import logging
import hashlib
import yaml


def temporary_save(fixer_response, project_meta):
    with open(f"temp/fixer/{project_meta['project_name']}_{project_meta['buggy_number']}.patch") as wf:
        wf.write(fixer_response["aim"])
    with open(f"temp/fixer/{project_meta['project_name']}_{project_meta['buggy_number']}.txt") as wf:
        wf.write(fixer_response["ori"])

def read_yaml(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def get_content(file_path: str):
    """Get the content in a given file path"""
    if not os.path.exists(file_path):
        return {"content": "", "err": f"{file_path} does not exist"}
    if os.path.isfile(file_path):
        with open(file_path) as rf:
            return json.dumps({"content": rf.read(), "err": ""})
    else:
        return {"content": "", "err": f"{file_path} is not a file"}


def read_json(filepath):
    if os.path.exists(filepath):
        assert filepath.endswith('.json')
        with open(filepath, 'r') as f:
            return json.loads(f.read())
    else: 
        raise ValueError("File path "+filepath+" not exists!")
        return
    
def json_pretty_dump(obj, filename):
    with open(filename, "w") as fw:
        json.dump(obj, fw, sort_keys=True, indent=4,
            separators=(",", ": "), ensure_ascii=False,)

def logging_activate(record_dir):
    os.makedirs(record_dir, exist_ok=True)
    log_file = os.path.join(record_dir, "running.log")
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s P%(process)d %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

def dump_exp(result_save_dir:str, params:dict):
    hash_id = hashlib.md5(str(sorted([(k, v) for k, v in params.items()])).encode("utf-8")).hexdigest()[0:8]
    record_dir = os.path.join(result_save_dir, hash_id)
    os.makedirs(record_dir, exist_ok=True)

    json_pretty_dump(params, os.path.join(record_dir, "params.json"))
    logging_activate(record_dir)
    return record_dir, hash_id

def return_lines(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as rf:
            return rf.read().splitlines()
    return []

def write_line(file_path, line):
    with open(file_path, "a+") as wf:
        wf.write(line+"\n")