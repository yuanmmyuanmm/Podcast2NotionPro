import argparse
import json
import os
import re
import time
import emoji
import pendulum
from retrying import retry
import requests
from notion_helper import NotionHelper
import utils
from dotenv import load_dotenv
import urllib.parse

load_dotenv()


headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://tongyi.aliyun.com",
    "priority": "u=1, i",
    "referer": "https://tongyi.aliyun.com/efficiency/doc/transcripts/g2y8qeaoogbxnbeo?source=2",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "x-b3-sampled": "1",
    "x-b3-spanid": "540e0d18e52cdf0d",
    "x-b3-traceid": "75a25320c048cde87ea3b710a65d196b",
    "x-tw-canary": "",
    "x-tw-from": "tongyi",
}


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def get_dir():
    """获取文件夹"""
    url = (
        "https://qianwen.biz.aliyun.com/assistant/api/record/dir/list/get?c=tongyi-web"
    )
    response = requests.post(url, headers=headers)
    if response.ok:
        r = response.json()
        success = r.get("success")
        errorMsg = r.get("errorMsg")
        if success:
            return r.get("data")

        else:
            print(f"请求失败：{errorMsg}")
    else:
        print("请求失败：", response.status_code)


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def dir_list(dir_id):
    """获取文件夹内所有的item"""
    result = []
    pageNo = 1
    pageSize = 48
    while True:
        payload = {
            "dirIdStr": dir_id,
            "pageNo": pageNo,
            "pageSize": pageSize,
            "status": [20, 30, 40, 41],
        }
        url = "https://qianwen.biz.aliyun.com/assistant/api/record/list?c=tongyi-web"
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            batchRecord = response.json().get("data").get("batchRecord")
            if len(batchRecord) == 0:
                break
            for i in batchRecord:
                result.extend(i.get("recordList"))
            pageNo += 1
        else:
            print("请求失败：", response.status_code)
            break
    return result


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def get_note(transId):
    """暂时不支持子list和表格"""
    url = "https://tw-efficiency.biz.aliyun.com/api/doc/getTransDocEdit?c=tongyi-web"
    payload = {"action": "getTransDocEdit", "version": "1.0", "transId": transId}
    response = requests.post(url, headers=headers, json=payload)
    if response.ok:
        note = response.json().get("data").get("content")
        if note:
            data = json.loads(note)
            children = []
            for paragraph in data:
                type = "paragraph"
                skip_outer = False
                is_checked = False
                rich_text = []
                if isinstance(paragraph, list):
                    for span in paragraph:
                        if isinstance(span, dict):
                            if "list" in span:
                                type = "bulleted_list_item"
                                isOrdered = span.get("list").get("isOrdered")
                                isTaskList = span.get("list").get("isTaskList")
                                if isOrdered:
                                    type = "numbered_list_item"
                                if isTaskList:
                                    type = "to_do"
                                    is_checked = span.get("list").get("isChecked")
                        if isinstance(span, list):
                            if span[0] == "span":
                                for i in range(2, len(span)):
                                    bold = False
                                    highlight = False
                                    content = span[i][2]
                                    if "bold" in span[i][1]:
                                        bold = span[i][1].get("bold")
                                    if "highlight" in span[i][1]:
                                        highlight = True
                                    rich_text.append(get_text(content, bold, highlight))
                            if span[0] == "tag":
                                time = utils.format_milliseconds(
                                    span[1].get("metadata").get("time")
                                )
                                rich_text.append(
                                    {
                                        "type": "text",
                                        "text": {"content": time},
                                        "annotations": {
                                            "underline": True,
                                            "color": "blue",
                                        },
                                    }
                                )
                            if span[0] == "img":
                                skip_outer = True
                                url = span[1].get("src")
                                children.append(
                                    {
                                        "type": "image",
                                        "image": {
                                            "type": "external",
                                            "external": {"url": url},
                                        },
                                    }
                                )
                if skip_outer:
                    continue
                child = {
                    "type": type,
                    type: {"rich_text": rich_text, "color": "default"},
                }
                if type == "to_do":
                    child[type]["checked"] = is_checked
                children.append(child)
            return children
    else:
        print("请求失败")


def get_text(content, bold=False, highlight=False):
    text = {"type": "text", "text": {"content": content}, "annotations": {"bold": bold}}
    if highlight:
        text["annotations"]["color"] = "red_background"
    return text


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def get_all_lab_info(transId):
    url = "https://tw-efficiency.biz.aliyun.com/api/lab/getAllLabInfo?c=tongyi-web"
    payload = {
        "action": "getAllLabInfo",
        "content": ["labInfo", "labSummaryInfo"],
        "transId": transId,
    }
    response = requests.post(url, headers=headers, json=payload)
    mindmap = None
    children = []
    if response.status_code == 200:
        data = response.json().get("data")
        labInfo = data.get("labCardsMap").get("labInfo")
        labInfo.extend(data.get("labCardsMap").get("labSummaryInfo"))
        for i in labInfo:
            name = i.get("basicInfo").get("name")
            if name == "qa问答":
                children.append(utils.get_heading(2, "问题回顾"))
            if name == "议程":
                children.append(utils.get_heading(2, "章节速览"))
            for content in i.get("contents", []):
                for contentValue in content.get("contentValues"):
                    if name == "全文摘要":
                        value = contentValue.get("value")
                        children.append(utils.get_heading(3, "全文摘要"))
                        children.append(utils.get_callout(value, {"emoji": "💡"}))
                    if name == "思维导图":
                        mindmap = contentValue.get("json")
                    if name == "议程":
                        title = f"{utils.format_milliseconds(contentValue.get('time'))} {contentValue.get('value')}"
                        children.append(utils.get_heading(3, title))
                        summary = contentValue.get("summary")
                        if summary:
                            children.append(utils.get_callout(summary, {"emoji": "💡"}))
                    if name == "qa问答":
                        title = contentValue.get("title")
                        value = contentValue.get("value")
                        beginTime = (
                            contentValue.get("extensions")[0]
                            .get("sentenceInfoOfAnswer")[0]
                            .get("beginTime")
                        )
                        beginTime = utils.format_milliseconds(beginTime)
                        title = f"{beginTime} {title}"
                        children.append(utils.get_heading(3, title))
                        children.append(utils.get_callout(value, {"emoji": "💡"}))
        return (children, mindmap)
    else:
        print("请求脑图失败：", response.status_code)


def insert_mindmap(block_id, children):
    """插入思维导图"""
    blocks = [utils.get_bulleted_list_item(block.get("content")) for block in children]
    results = notion_helper.append_blocks(
        block_id=block_id,
        children=blocks,
    ).get("results")
    for index, child in enumerate(children):
        if child.get("children"):
            insert_mindmap(results[index].get("id"), child.get("children"))


def check_mindmap(title):
    """检查是否已经插入过"""
    filter = {"property": "标题", "title": {"equals": title}}
    response = notion_helper.query(
        database_id=notion_helper.mindmap_database_id, filter=filter
    )
    if len(response["results"]) > 0:
        return response["results"][0]


def create_mindmap(title, icon):
    result = check_mindmap(title)
    if result:
        status = utils.get_property_value(result.get("properties").get("状态"))
        if status == "Done":
            return result.get("id")
        else:
            notion_helper.delete_block(result.get("id"))
    parent = {
        "database_id": notion_helper.mindmap_database_id,
        "type": "database_id",
    }
    properties = {
        "标题": {"title": [{"type": "text", "text": {"content": title}}]},
        "状态": {"status": {"name": "In progress"}},
    }

    mindmap_page_id = notion_helper.create_page(
        parent=parent,
        properties=properties,
        icon=icon,
    ).get("id")
    return mindmap_page_id


def update_mindmap(page_id):
    properties = {
        "状态": {"status": {"name": "Done"}},
    }

    notion_helper.update_page(
        page_id=page_id,
        properties=properties,
    )


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def get_trans_result(transId):
    payload = {
        "action": "getTransResult",
        "version": "1.0",
        "transId": transId,
    }
    url = "https://tw-efficiency.biz.aliyun.com/api/trans/getTransResult?c=tongyi-web"
    response = requests.post(url, headers=headers, json=payload)

    if response.ok:
        response_data = response.json()
        user_dict = {}
        if response_data.get("data").get("tag").get("identify"):
            user_info = json.loads(
                response_data.get("data").get("tag").get("identify")
            ).get("user_info")
            for key, value in user_info.items():
                user_dict[key] = value.get("name")
        children = []
        for i in json.loads(response_data.get("data").get("result")).get("pg"):
            content = ""
            name = ""
            uid = i.get("ui")
            avatar = None
            if uid in user_dict:
                name = user_dict.get(uid)
                avatar = get_author_avatar(name)
            else:
                name = f"发言人{uid}"
            if avatar is None:
                avatar = "https://www.notion.so/icons/user_gray.svg"
            title = f'{name} {utils.format_milliseconds(i.get("sc")[0].get("bt"))}'
            children.append(utils.get_heading(3, title))
            for j in i.get("sc"):
                content += j.get("tc")
            children.append(utils.get_callout(content, utils.get_icon(avatar)))
        return children
    else:
        print("请求失败：", response.status_code)
        return None


author_cache = {}


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def get_author_avatar(author):
    if author in author_cache:
        return author_cache[author]
    filter = {"property": "标题", "title": {"equals": author}}
    r = notion_helper.query(database_id=notion_helper.author_database_id, filter=filter)
    if len(r.get("results")) > 0:
        avatar = r.get("results")[0].get("icon").get("external").get("url")
        author_cache[author] = avatar
        return avatar


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def create_dir(name):
    """创建文件夹，支持创建重名文件夹"""
    payload = {"dirName": name, "parentIdStr": -1}
    url = "https://qianwen.biz.aliyun.com/assistant/api/record/dir/add?c=tongyi-web"
    r = requests.post(url, headers=headers, json=payload)
    if r.ok:
        return r.json().get("data").get("focusDir").get("idStr")


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def parseNetSourceUrl(rss_url):
    print("start parse url")
    payload = {"action": "parseNetSourceUrl", "version": "1.0", "url": rss_url}
    url = (
        "https://tw-efficiency.biz.aliyun.com/api/trans/parseNetSourceUrl?c=tongyi-web"
    )
    r = requests.post(url, headers=headers, json=payload)
    if r.ok:
        print("parse url success")
        return r.json().get("data").get("taskId")


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def start(dir_id, files):
    payload = {
        "dirIdStr": dir_id,
        "files": files,
        "taskType": "net_source",
        "bizTerminal": "web",
    }
    url = "https://qianwen.biz.aliyun.com/assistant/api/record/blog/start?c=tongyi-web"
    response = requests.post(url, headers=headers, json=payload)


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def queryNetSourceParse(task_id, dir_id):
    payload = {"action": "queryNetSourceParse", "version": "1.0", "taskId": task_id}
    url = "https://tw-efficiency.biz.aliyun.com/api/trans/queryNetSourceParse?c=tongyi-web"
    response = requests.post(url, headers=headers, json=payload)
    results = []
    if response.ok:
        data = response.json().get("data")
        status = data.get("status")
        print(f"query source status {status}")
        if status == 0:
            urls = data.get("urls")
            for url in urls:
                results.append(
                    {
                        "fileId": url.get("fileId"),
                        "dirId": dir_id,
                        "fileSize": url.get("size"),
                        "tag": {
                            "fileType": "net_source",
                            "showName": url.get("showName"),
                            "lang": "cn",
                            "roleSplitNum": 0,
                            "translateSwitch": 0,
                            "transTargetValue": 0,
                            "client": "web",
                            "originalTag": "",
                        },
                    }
                )
            return results
        elif status == -1:
            time.sleep(1)
            return queryNetSourceParse(task_id=task_id, dir_id=dir_id)
        else:
            print(f"query source data = {status}")
            return None


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def start_trans(dir_name, rss):
    print(f"开始转写{dir_name}")
    dir = list(filter(lambda x: x.get("dir").get("dirName") == dir_name, all_dirs))
    if len(dir) > 0:
        dir_str_id = dir[0].get("dir").get("idStr")
    else:
        dir_str_id = create_dir(dir_name)
    task_id = parseNetSourceUrl(rss)
    files = queryNetSourceParse(task_id=task_id, dir_id=dir_str_id)
    for i in range(0, len(files) // 50 + 1):
        start(dir_id=dir_str_id, files=files[i * 50 : (i + 1) * 50])


cache = {}


def get_podcast(ids):
    podcast_page_id = podcast[0].get("id")
    if id not in cache:
        podcast_properties = notion_helper.client.pages.retrieve(podcast_page_id).get(
            "properties"
        )
        cache[podcast_page_id] = podcast_properties
    return cache.get(podcast_page_id)


if __name__ == "__main__":
    notion_helper = NotionHelper()
    headers["cookie"] = os.getenv("COOKIE").strip()
    f = {
        "and": [
            {"property": "语音转文字状态", "status": {"does_not_equal": "Done"}},
        ]
    }
    episodes = notion_helper.query_all_by_filter(
        notion_helper.episode_database_id, filter=f
    )
    print(f"获取播客成功：{len(episodes)}")
    records = []
    all_dirs = get_dir()
    if all_dirs:
        for i in all_dirs:
            records.extend(dir_list(i.get("dir").get("id")))
    records = {x.get("recordTitle"): x for x in records if x.get("recordStatus") != 40}
    print(f"获取所有转写记录：{len(records)}")
    results = {}
    for episode in episodes:
        episode_properties = episode.get("properties")
        podcast = utils.get_property_value(episode_properties.get("Podcast"))
        podcast_properties = get_podcast(podcast)
        podcast_title = utils.get_property_value(podcast_properties.get("播客"))
        rss = utils.get_property_value(podcast_properties.get("rss"))
        title = utils.get_property_value(episode_properties.get("标题"))
        children = []
        # 20 正在转 30是成功 40是失败
        if title not in results:
            title = emoji.replace_emoji(title, replace="")
            title = re.sub(r"\s+", " ", title).strip()
        if title in records:
            if records.get(title).get("recordStatus") != 30:
                continue
            episode_page_id = episode.get("id")
            audio_url = utils.get_property_value(episode_properties.get("音频"))
            transId = records.get(title).get("genRecordId")
            cover = episode.get("cover").get("external").get("url")
            children.append(utils.get_heading(2, "音频"))
            player_url = f"https://notion-music.malinkang.com/player?url={urllib.parse.quote(audio_url)}&name={urllib.parse.quote(title)}&cover={urllib.parse.quote(cover)}&artist={urllib.parse.quote(podcast_title)}"
            children.append({"type": "embed", "embed": {"url": player_url}})
            print(f"开始获取《{title}》的数据")
            info, mindmap = get_all_lab_info(transId)
            mindmap_page_id = None
            if mindmap:
                mindmap_page_id = create_mindmap(title, episode.get("icon"))
                start = time.time()
                print(f"开始插入思维导图")
                mindmap_root_id = (
                    notion_helper.append_blocks(
                        block_id=mindmap_page_id,
                        children=[utils.get_bulleted_list_item(mindmap.get("content"))],
                    )
                    .get("results")[0]
                    .get("id")
                )
                insert_mindmap(mindmap_root_id, mindmap.get("children"))
                update_mindmap(mindmap_page_id)
                end = time.time()
                print(f"插入思维导图结束 {end-start}")
                mindmap_url = f"https://mindmap.malinkang.com/markmap/{mindmap_page_id.replace('-','')}?token={os.getenv('NOTION_TOKEN')}"
                children.append(utils.get_heading(2, "思维导图"))
                children.append({"type": "embed", "embed": {"url": mindmap_url}})
            if info:
                children.extend(info)
            trans = get_trans_result(transId)
            if trans:
                children.append(utils.get_heading(2, "语音转文字"))
                children.extend(trans)
            note = get_note(transId)
            if note:
                children.append(utils.get_heading(2, "笔记"))
                children.extend(note)
            start = time.time()
            print(f"开始插入其他数据")
            for i in range(0, len(children) // 100 + 1):
                notion_helper.append_blocks(
                    block_id=episode_page_id, children=children[i * 100 : (i + 1) * 100]
                )
            end = time.time()
            print(f"插入其他数据结束 {end-start}")
            properties = {"语音转文字状态": {"status": {"name": "Done"}}}
            if mindmap_page_id:
                properties["思维导图"] = {"relation": [{"id": mindmap_page_id}]}
            notion_helper.update_page(
                page_id=episode_page_id,
                properties=properties,
            )
        else:
            if podcast_title and rss:
                if podcast_title not in results:
                    results[podcast_title] = rss
    for key, value in results.items():
        start_trans(key, value)
