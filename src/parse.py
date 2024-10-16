import re
import logging

class NoCodeError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

def parse_code(text):
    tmp = []
    for pattern in [r'```(?:[^\n]*\n)?(.*?)```', r'```(?:[^\n]*\n)?(.*?)===', r'^(.*?)```' ,r'`(?:[^\n]*\n)?(.*?)`', r'```(?:[^\n]*\n)?(.*?)$']:
        tmp = re.findall(pattern, text, re.DOTALL)
        if len(tmp) > 0 and len(tmp[0]) > 0:
            break
    if len(tmp) == 0: #Cannot find valid code
        raise NoCodeError("Cannot extract any code from:\n@@@@@\n"+text+"\n@@@@@\n")
    return tmp

def parse_exp(text):
    tmp = []
    for pattern in [r'===(?:[^\n]*\n)?(.*?)===', r'===(?:[^\n]*\n)?(.*?)$', r'^(?:[^\n]*\n)?(.*?)```']:
        tmp = re.findall(pattern, text, re.DOTALL)
        if len(tmp) > 0: break

    if len(tmp) == 0:
        logging.warning("This response doesn't explain the repairing")
        return ""
    else:
        return "\n".join(tmp)

def remove_comment(code):
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    code = re.sub(r'//.*', '', code)
    return re.sub(r'^\s*$', '', code, flags=re.MULTILINE) #Remove empty lines

def remove_whitespace(line: str) -> str:
    return line.replace('\n', '').replace(' ', '')

def two_lines_match(line1: str, line2: str): # Match: two strings are equal ignoring comments and whitespaces
    if line1 is None or line2 is None: return False
    if line1.strip().startswith("//") and line2.strip().startswith("//"):
        return remove_whitespace(line1) == remove_whitespace(line2)
    return remove_whitespace(line1.split("//")[0]) == remove_whitespace(line2.split("//")[0])

# def insert_lists(big_list, insertions):
#     insertions.sort(key=lambda x: x[1], reverse=True)
#     for small_list, index in insertions:
#         big_list[index:index] = small_list
#     return big_list

def is_valid_line(line):
    return len(remove_whitespace(line)) > 3 and line.strip()[0] != "+" and "missing" not in line and "buggy" not in line

def search_valid_line(lines: list[str], start_idx: int, mode, degree=1): # Valid: Not a edited or empty line
    incre = -1 if mode == "pre" else 1
    cur_idx = start_idx + incre
    valid_lines = []
    while cur_idx >= 0 and cur_idx < len(lines):
        if is_valid_line(lines[cur_idx]):
            valid_lines.append((lines[cur_idx], cur_idx))
            if len(valid_lines) == degree:
                break
        cur_idx += incre
    return valid_lines #valid and valid_index

def matching_with_comments(aim_line, matched, code_lines): # Perfect match: two strings are equal ignoring whitespaces
    match_perfect = []
    for match_idx in matched:
        if remove_whitespace(aim_line) == remove_whitespace(code_lines[match_idx]):
            match_perfect.append(match_idx)
    return match_perfect

def matching_lines(aim_line, code_lines, stop_at_first_match=False): # return all matched lines
    if aim_line is None: return []
    matched = []
    for idx, cl in enumerate(code_lines): 
        if two_lines_match(aim_line, cl):
            matched.append(idx)
            if stop_at_first_match: return [idx]
    return matched

def matching_neighbor(aim_codes: list[str], aim_idx: int, raw_codes: list[str], matched: list[int], mode: str, match_limit=1, degree_limit=5) -> list[str]:
    '''
    For multiple matches, check the neighboring valid lines.
    For example: 
    We want to match a hunk of 
    for i in range(1, 10):
        print(i)
    The aim line is `print(i)` so matched is [4, 9].
        3. for i in range(1, 10):
        4.    print(i)
    vs.
        8. for i in range(5):
        9.    print(i)
    Then we check whether 3 and 8 correspond the (pre)neibor of the aim line
    Args:
        neibor_line: a valid neighboring line of the target line
        code_lines: original code lines to be matched
        matched: index in code_lines of the matched code
        mode: pre or post
    Returns:
        Total number of lines matched with neighboring lines
    '''

    for degree in range(1, degree_limit+1):
        neibor_also_match = []
        for match_idx in matched:
            aim_neibor = search_valid_line(aim_codes, aim_idx, mode, degree=degree)
            match_neibor = search_valid_line(raw_codes, match_idx, mode, degree=degree)
            match_flag = True
            for k in range(degree):
                if not two_lines_match(aim_neibor[k][1], match_neibor[k][1]):
                    match_flag = False
                    break
            if match_flag:
                neibor_also_match.append(match_idx)

        if len(neibor_also_match) <= match_limit:
            return neibor_also_match


def unique_matching(resp_lines, code_lines, resp_cur_idx, resp_cur_line=None):
    resp_cur_line = resp_lines[resp_cur_idx] if resp_cur_line is None else resp_cur_line
    matched = matching_lines(resp_cur_line, code_lines)
    if len(matched) == 1: return matched[0]
    if len(matched) == 0: return -1

    for degree_limit in range(1, 5):
        post_match = matching_neighbor(resp_lines, resp_cur_idx, code_lines, matched, mode="post", degree_limit=degree_limit, match_limit=5)
        if len(post_match) == 1: return post_match[0]
        pre_match = matching_neighbor(resp_lines, resp_cur_idx, code_lines, matched, mode="pre", degree_limit=degree_limit, match_limit=5)
        if len(pre_match) == 1: return pre_match[0]
        if len(set(pre_match) & set(post_match)) == 1:
            return list(set(pre_match) & set(post_match))[0]
        
    return -1


if __name__ == "__main__":
    aim_line = "int g = (int) ((value - this.lowerBound) / (this.upperBound - this.lowerBound) * 255.0); // buggy line"





