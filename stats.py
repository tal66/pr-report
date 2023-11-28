import logging
import os
from datetime import datetime, timedelta
from textwrap import dedent
from urllib.parse import urlparse

import requests
from jinja2 import Template

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.DEBUG)

AUTHOR = "tal66"
MAX_PAGES = 10
PER_PAGE = 40
STALE_AFTER_DAYS = 40
BASE_URL = "https://api.github.com/search/issues"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


class PR:
    def __init__(self, title, *, repo=None, url=None, merged_at=None, created_at=None, state=None) -> None:
        self.title = title
        self.repo = repo
        self.url = url
        self.merged_at = merged_at
        self.created_at = created_at
        self.state = state

    def is_closed(self):
        return self.state == "closed"

    @classmethod
    def from_github_item(cls, item):
        """returns new PR"""
        result = PR(title=item["title"])
        repo_url = item["repository_url"]
        item_pr = item["pull_request"]
        result.repo = PR._get_repo_name(repo_url)
        result.url = item_pr["html_url"]
        result.merged_at = PR._format_date(item_pr["merged_at"])
        result.created_at = PR._format_date(item["created_at"])
        result.state = item["state"]
        return result

    @staticmethod
    def _get_repo_name(repo_url) -> str:
        """url -> org/repo"""
        parsed_url = urlparse(repo_url)
        url_parts = parsed_url.path.split("/")
        if len(url_parts) == 4 and url_parts[1] == "repos":
            owner = url_parts[2]
            repo = url_parts[3]
            return f"{owner}/{repo}"
        return repo_url

    @staticmethod
    def _format_date(date: str) -> str:
        if not date:
            return date
        date_only = datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
        return date_only


def fetch_data() -> list:
    """
    fetch PR's by AUTHOR from github.
    w/o token => rate limit 10 pages/minute.
    with token => rate limit 30 pages/minute.
    """
    result = []
    page_num = 0
    with requests.Session() as session:
        while page_num < MAX_PAGES:
            page_num += 1
            logging.info(f"fetching page {page_num}")

            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            if not GITHUB_TOKEN:
                headers = {}

            # get
            response = session.get(
                f"{BASE_URL}?q=is:pr+author:{AUTHOR}&per_page={PER_PAGE}&page={page_num}", headers=headers
            )
            if not response.ok:
                logging.error(f"{response.status_code} {response.reason}. {response.text}")
                return []
            logging.debug(f"X-Ratelimit-Remaining {response.headers.get('X-Ratelimit-Remaining')}")
            data = response.json()
            items = data.get("items", [])
            logging.debug(f'items count: {len(items)} / total count: {data["total_count"]}')

            if data["incomplete_results"]:
                logging.warning("incomplete results")

            # save
            result.extend(items)

            if not items or (data["total_count"] == len(result)):
                break

    if data["total_count"] > len(result):
        logging.warning(f"partial: fetched {len(result)} / total {data['total_count']}")

    return result


def parse_data(items: list) -> list[PR]:
    stale_count = 0
    user_own_repo_count = 0
    parsed_items = []

    for item in items:
        pr = PR.from_github_item(item)

        if pr.repo.startswith(f"{AUTHOR}/"):
            user_own_repo_count += 1

        if is_stale(pr):
            stale_count += 1

        parsed_items.append(pr)

    count = len(parsed_items)
    logging.info(f"summary [total: {count}, stale: {stale_count}, user owned repos: {user_own_repo_count}]")

    return parsed_items


def gen_readme(items: list[PR]):
    logging.info(f"generating report for {len(items)} items")

    template_str = dedent(
        """\
            ## Pull Request Report
            Date: {{ today }}
            
            User: {{ author }}
            
            ### Pull Requests
            {% for pr in items %}
            ### [{{ pr.title }}]({{ pr.url }})
            
            **Repo:** {{ pr.repo }}
            
            **Merged:** {% if pr.merged_at %}{{ pr.merged_at }}
            {% elif not pr.is_closed() %}Pending (Created: {{ pr.created_at }})
            {% else %}Closed {% endif %}
            
            {% endfor %}
        """
    )

    today = datetime.utcnow().strftime("%Y-%m-%d")
    template = Template(template_str)
    result = template.render(items=items, today=today, author=AUTHOR)

    filename = "README.md"
    with open(filename, "w") as readme_file:
        readme_file.write(result)
    logging.info(f"{filename} generated")


def is_stale(pr: PR) -> bool:
    """stale if probably not going to be merged (closed or time passed)"""
    created_at_dt = datetime.strptime(pr.created_at, "%Y-%m-%d")
    diff = datetime.utcnow() - created_at_dt
    expired = diff > timedelta(days=STALE_AFTER_DAYS)
    closed = pr.state == "closed"
    return (expired or closed) and (pr.merged_at is None)


if __name__ == "__main__":
    items = fetch_data()
    if not items:
        exit(1)
    parsed_items = parse_data(items)
    gen_readme(parsed_items)
