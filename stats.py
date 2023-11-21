import logging
from datetime import datetime, timedelta
from typing import List
from urllib.parse import urlparse

import requests

logging.basicConfig(format='%(levelname)s: %(message)s', encoding='utf-8', level=logging.DEBUG)

author = "tal66"
max_pages = 10
stale_after_days = 30
base_url = f'https://api.github.com/search/issues'


class PR:
    def __init__(self, title, repo, url, merged_at, created_at) -> None:
        self.title = title
        self.repo = repo
        self.url = url
        self.merged_at = merged_at
        self.created_at = created_at


def fetch_data() -> list:
    result = []
    page_num = 0
    with requests.Session() as session:
        while page_num < max_pages:
            page_num += 1
            logging.info(f"fetching page {page_num}")

            # get
            response = session.get(f"{base_url}?q=is:pr+author:{author}&page={page_num}")
            logging.debug(f"response {response.status_code}")
            data = response.json()
            items = data.get('items', [])
            logging.debug(f'items count: {len(items)} / total count: {data["total_count"]}')

            if not items:
                break

            if data["incomplete_results"]:
                logging.warning("incomplete results")

            # save
            result.extend(items)

    return result


def parse_data(items: list) -> List[PR]:
    count = 0
    skip_count = 0
    parsed_items = []

    for item in items:
        title = item["title"]
        repo_url = item["repository_url"]
        repo_name = get_repo_name(repo_url)
        pr = item["pull_request"]
        pr_url = pr["url"]
        merged_at = pr["merged_at"]
        if merged_at:
            merged_at = format_date(merged_at)
        created_at = format_date(item["created_at"])

        if is_stale(created_at, merged_at):
            skip_count += 1
            continue
        count += 1

        parsed_items.append(PR(title=title, repo=repo_name, url=pr_url, merged_at=merged_at, created_at=created_at))

    logging.info(f"count: {count}. skip: {skip_count}")
    return parsed_items


def gen_readme(items: list[PR]):
    logging.info(f"generating report for {len(items)} items")
    from jinja2 import Template

    template_str = """
## Pull Request Report
Date: {{ today }}

User: {{ author }}

### Pull Requests
{% for pr in items %}
### [{{ pr.title }}]({{ pr.url }})

- **Repository:** {{ pr.repo }}
- **Merged At:** {% if pr.merged_at %}{{ pr.merged_at }}{% else %}Not Merged Yet{% endif %}
{% if not pr.merged_at %}- **Created At:** {{ pr.created_at }}{% endif %}

{% endfor %}
"""

    today = datetime.utcnow().strftime('%Y-%m-%d')
    template = Template(template_str)
    result = template.render(items=items, today=today, author=author)

    with open("README.md", "w") as readme_file:
        readme_file.write(result)

    logging.info("README.md generated")


def is_stale(created_at, merged_at) -> bool:
    created_at_datetime = datetime.strptime(created_at, "%Y-%m-%d")
    difference = datetime.utcnow() - created_at_datetime
    return difference > timedelta(days=stale_after_days) and merged_at is None


def get_repo_name(repo_url) -> str:
    parsed_url = urlparse(repo_url)
    url_parts = parsed_url.path.split('/')
    if len(url_parts) == 4 and url_parts[1] == 'repos':
        owner = url_parts[2]
        repo = url_parts[3]
        return f"{owner}/{repo}"
    return repo_url


def format_date(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ").strftime('%Y-%m-%d')


if __name__ == '__main__':
    items = fetch_data()
    parsed_items = parse_data(items)
    gen_readme(parsed_items)
