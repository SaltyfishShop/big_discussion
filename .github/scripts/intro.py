import glob
import json
import logging
import os
import re
import uuid
from datetime import datetime

import requests
from github import Github

logger = logging.getLogger(__file__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

GITHUB_TOKEN = os.environ["INTRO_TOKEN"]
REPO_URL = "SaltyfishShop/Introduce-Yourself"
REPO_NAME = os.environ["GITHUB_REPOSITORY"]
DISCUSSION_ID = os.environ["DISCUSSION_ID"]
COMMENT_ID = os.environ["COMMENT_ID"]
ACTION_TYPE = os.environ["EVENT_NAME"]
COMMENT_CONTENT = os.environ["COMMENT_CONTENT"]
COMMENT_LINK = os.environ["COMMENT_LINK"]
COMMENT_ACTOR = os.environ["GITHUB_ACTOR"]

# Initialize GitHub client
gh = Github(GITHUB_TOKEN)
repo = gh.get_repo(REPO_URL)

# Create a new branch
branch_name = f"comment-{COMMENT_ID}-{uuid.uuid4().hex[:6]}"
base_sha = repo.get_branch("main").commit.sha
repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
logger.info(f"created new branch {branch_name}")

# Handle file based on the action
file_name_candidates = glob.glob(f"members/*-{COMMENT_ID}.json")
file_found = False
if file_name_candidates:
    file_path = file_name_candidates[0]
    file_found = True
else:
    file_path = f"members/{COMMENT_ACTOR}-{COMMENT_ID}.json"
logger.info(f"file_found: {file_found}, file_path: {file_path}, ACTION_TYPE = {ACTION_TYPE}")

try:
    if ACTION_TYPE == "created" or ACTION_TYPE == "edited":
        if not COMMENT_CONTENT.startswith("###"):
            raise ValueError("内容应当以三级标题 `###` 开头。请修改你的评论。")
        if re.search(r'\n#{1,3}\s', COMMENT_CONTENT[3:]):
            raise ValueError("内容中不应包含三级和三级以上的标题。请修改你的评论。")
        if "\n---" in COMMENT_CONTENT:
            raise ValueError("内容中不应包含分页符。请修改你的评论。")

    if ACTION_TYPE == "created" or (ACTION_TYPE == "edited" and not file_found):
        current_time = datetime.utcnow().isoformat() + "Z"
        content_data = {
            "comment_id": COMMENT_ID,
            "content": COMMENT_CONTENT,
            "created_at": current_time,
            "edited_at": current_time,
        }
        logger.info(f"creating {file_path}: \n{content_data}")
        commit_info = repo.create_file(
            file_path, f"Add comment data for {COMMENT_ID}", json.dumps(content_data, indent=4, ensure_ascii=False), branch=branch_name
        )
        logger.info(f"Commit SHA: {commit_info['commit'].sha}, Commit URL: {commit_info['commit'].url}")

    elif ACTION_TYPE == "edited":
        contents = repo.get_contents(file_path, ref=branch_name)
        file_content = contents.decoded_content.decode("utf-8")
        json_data = json.loads(file_content)
        json_data["content"] = COMMENT_CONTENT
        json_data["edited_at"] = datetime.utcnow().isoformat() + "Z"
        logger.info(f"updating {file_path}: \n{json_data}")
        commit_info = repo.update_file(
            file_path,
            f"Update comment data for {COMMENT_ID}",
            json.dumps(json_data, indent=4, ensure_ascii=False),
            sha=repo.get_contents(file_path).sha,
            branch=branch_name,
        )
        logger.info(f"Commit SHA: {commit_info['commit'].sha}, Commit URL: {commit_info['commit'].url}")

    elif ACTION_TYPE == "deleted" and file_found:
        logger.info(f"deleting {file_path}")
        commit_info = repo.delete_file(
            file_path, f"Delete comment data for {COMMENT_ID}", sha=repo.get_contents(file_path).sha, branch=branch_name
        )
        logger.info(f"Commit SHA: {commit_info['commit'].sha}, Commit URL: {commit_info['commit'].url}")

    elif ACTION_TYPE == "deleted" and not file_found:
        raise RuntimeError("ACTION_TYPE 为 delete，但没有找到对应文件")
    
    else:
        raise NotImplementedError("未知错误")

    # Create a pull request
    pr = repo.create_pull(
        title=f"Changes for comment {COMMENT_ID}",
        body=f"处理的评论: {COMMENT_LINK}\n\n事件类型: {ACTION_TYPE}\n触发者: {COMMENT_ACTOR}\n\n内容:\n{COMMENT_CONTENT}",
        head=branch_name,
        base="main",
    )
    logger.info(f"PR created: {pr.html_url}")
    message_body = f"[bot] 欢迎来到咸鱼肆！Pipeline 已创建 [PR]({pr.html_url}) 来将你的自我介绍合入，请耐心等待 review~"
except Exception as e:
    logger.error(f"Error during the process: {e}")
    message_body = f"[bot] Pipeline 异常退出，详情：\n{type(e).__name__}: {e}"
    exit(1)
finally:
    # find comment Node ID
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    query_comments = """
    {
        repository(owner: "SaltyfishShop", name: "big_discussion") {
            discussion(number: 5) {
                comments(first: 100) {
                    nodes {
                        id
                        url
                    }
                }
            }
        }
    }
    """
    response = requests.post(
        f"https://api.github.com/graphql",
        headers=headers,
        json={"query": query_comments},
    )
    comments = json.loads(response.content.decode())
    comments = comments["data"]["repository"]["discussion"]["comments"]["nodes"]
    comment_node_id = next((item["id"] for item in comments if item["url"].endswith(COMMENT_ID)), None)
    if not comment_node_id:
        raise RuntimeError(f"comment {COMMENT_ID} not found.")
    logger.info(f"Found comment Node ID = {comment_node_id}")

    # Notify user about PR or failure
    post_reply = f"""
    mutation {{
        addDiscussionComment(input:{{  
            discussionId: "D_kwDOIb6PHs4ASZ_A",
            replyToId: "{comment_node_id}", 
            body: \"""{message_body}\""", 
        }}) {{
            comment {{
                id
                body  
            }}
        }}
    }}
    """
    response = requests.post(
        f"https://api.github.com/graphql",
        headers=headers,
        json={"query": post_reply},
    )
    response.raise_for_status()
    logger.info(f"Reply sent. Responose: {response.content.decode()}")
