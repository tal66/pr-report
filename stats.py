import logging
import os
from datetime import datetime, timedelta
from textwrap import dedent
from urllib.parse import urlparse

import requests
from jinja2 import Template

logging.basicConfig(format='%(levelname)s: %(message)s', encoding='utf-8', level=logging.DEBUG)

AUTHOR = "tal66"
MAX_PAGES = 10
STALE_AFTER_DAYS = 30
BASE_URL = 'https://api.github.com/search/issues'
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', "")


class PR:
    def __init__(self, title, repo, url, merged_at, created_at) -> None:
        self.title = title
        self.repo = repo
        self.url = url
        self.merged_at = merged_at
        self.created_at = created_at

    @staticmethod
    def from_github_item(item):
        """returns new PR"""
        title = item["title"]
        repo_url = item["repository_url"]
        repo_name = PR._get_repo_name(repo_url)
        pr = item["pull_request"]
        pr_url = pr["html_url"]
        merged_at = PR._format_date(pr["merged_at"])
        created_at = PR._format_date(item["created_at"])
        return PR(title=title, repo=repo_name, url=pr_url, merged_at=merged_at, created_at=created_at)

    @staticmethod
    def _get_repo_name(repo_url) -> str:
        """url -> org/repo"""
        parsed_url = urlparse(repo_url)
        url_parts = parsed_url.path.split('/')
        if len(url_parts) == 4 and url_parts[1] == 'repos':
            owner = url_parts[2]
            repo = url_parts[3]
            return f"{owner}/{repo}"
        return repo_url

    @staticmethod
    def _format_date(date: str) -> str:
        if not date:
            return date
        date_only = datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ").strftime('%Y-%m-%d')
        return date_only


def fetch_data() -> list:
    """
    fetch PR's by AUTHOR from github.
    w/o token => rate limit 10 pages/minute.
    with token => rate limit 30 pages/minute
    """
    result = []
    page_num = 0
    with requests.Session() as session:
        while page_num < MAX_PAGES:
            page_num += 1
            logging.info(f"fetching page {page_num}")

            headers = {'Authorization': f'token {GITHUB_TOKEN}'}
            if not GITHUB_TOKEN:
                headers = {}

            # get
            response = session.get(f"{BASE_URL}?q=is:pr+author:{AUTHOR}&page={page_num}", headers=headers)
            if not response.ok:
                logging.error(f"{response.status_code} {response.reason}. {response.text}")
                return []
            logging.debug(f"X-Ratelimit-Remaining {response.headers.get('X-Ratelimit-Remaining')}")
            data = response.json()
            items = data.get('items', [])
            logging.debug(f'items count: {len(items)} / total count: {data["total_count"]}')

            if data["incomplete_results"]:
                logging.warning("incomplete results")

            # save
            result.extend(items)

            if not items or (data["total_count"] == len(result)):
                break

    return result


def parse_data(items: list) -> list[PR]:
    count = 0
    skip_count = 0
    parsed_items = []

    for item in items:
        pr = PR.from_github_item(item)

        if is_stale(pr.created_at, pr.merged_at):
            skip_count += 1
            continue
        count += 1

        parsed_items.append(pr)

    logging.info(f"count: {count}. skip: {skip_count}")
    return parsed_items


def gen_readme(items: list[PR]):
    logging.info(f"generating report for {len(items)} items")

    template_str = dedent("""\
                ## Pull Request Report
                Date: {{ today }}
                
                User: {{ author }}
                
                ### Pull Requests
                {% for pr in items %}
                ### [{{ pr.title }}]({{ pr.url }})
                
                **Repo:** {{ pr.repo }}
                
                **Merged:** {% if pr.merged_at %}{{ pr.merged_at }}{% else %}Pending{% endif %}
                {% if not pr.merged_at %} (Created: {{ pr.created_at }}){% endif %}
                
                {% endfor %}
                """)

    today = datetime.utcnow().strftime('%Y-%m-%d')
    template = Template(template_str)
    result = template.render(items=items, today=today, author=AUTHOR)

    with open("README.md", "w") as readme_file:
        readme_file.write(result)

    logging.info("README.md generated")


def is_stale(created_at, merged_at) -> bool:
    """stale if !merged && STALE_AFTER_DAYS"""
    created_at_dt = datetime.strptime(created_at, "%Y-%m-%d")
    diff = datetime.utcnow() - created_at_dt
    return diff > timedelta(days=STALE_AFTER_DAYS) and (merged_at is None)


if __name__ == '__main__':
    items = fetch_data()
    if not items:
        exit(1)
    parsed_items = parse_data(items)
    gen_readme(parsed_items)
