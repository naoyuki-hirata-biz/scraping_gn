"""Module providing a CsvCreator."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from abc import abstractmethod
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests_file import FileAdapter
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class CsvCreator:
    """Class for outputting Csv."""

    TIMEZONE = timezone(timedelta(hours=+9), 'JST')
    CSV_HEADER = ['店舗名', '電話番号', 'メールアドレス', '都道府県', '市区町村', '番地', '建物名', 'URL', 'SSL']

    def __init__(self, **kwargs):
        self.filename = kwargs['filename']
        self.uri = kwargs['uri']
        self.limit = kwargs['shops']
        self.timeout = kwargs['timeout']
        self.retry = kwargs['retry']

    def create(self) -> CsvCreator:
        """Output CSV file."""
        try:
            self._setUp()
            self._write_csv()
            self._tearDown()
        except Exception:  # pylint: disable=broad-exception-caught
            traceback.print_exc()
            self._on_error()

    @abstractmethod
    def _setUp(self):
        """setUp."""

    @abstractmethod
    def _tearDown(self):
        """tearDown."""

    def _on_error(self):
        """Cleaning up after an error."""
        if os.path.isfile(self.filename):
            os.remove(self.filename)

    @abstractmethod
    def _write_csv(self):
        """Write to CSV file"""

    @staticmethod
    def separate_address(address) -> list:
        """Separate addresses into prefecture, city, and street address."""
        pattern = r'(東京都|北海道|(?:京都|大阪)府|.{2,3}県)?(.+?)(\d.*)'
        match = re.match(pattern, address)
        return [match.group(1), match.group(2), match.group(3)]


class CsvCreatorFactory:
    """Factory class for CsvCreator."""

    @staticmethod
    def create_csv_creator(**kwargs) -> CsvCreator:
        """Returns an instance of CsvCreator."""

        lib = kwargs['lib']
        if lib == 'requests':
            return RequestsCsvCreator(**kwargs)
        if lib == 'selenium':
            return SeleniumCsvCreator(**kwargs)
        raise ValueError(f'Unknown type: {lib}')


class RequestsCsvCreator(CsvCreator):
    """CsvCreator for requests."""

    USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'

    # Override
    def _setUp(self):
        if os.path.isfile(self.filename):
            os.remove(self.filename)
        if self.uri.startswith('file:///opt/python/static/html/'):
            shutil.unpack_archive('static/html.zip', 'static/html')

    def __beautiful_soup_instance(self, url, page=None):
        session = requests.Session()
        if self.uri.startswith('http'):
            target_url = f'{url}&p={page}' if page else url
            res = session.get(target_url, headers={'User-Agent': self.USER_AGENT})
            return BeautifulSoup(res.content, 'html.parser')

        parsed_url = urlparse(url)
        original_filename = os.path.basename(parsed_url.path)
        filename, file_extension = os.path.splitext(original_filename)
        if page:
            filename = filename.split('_')[0] + '_' + filename.split('_')[1] + '_' + str(page).zfill(2) + file_extension
            target_url = url.replace(original_filename, filename)
        else:
            target_url = url

        session.mount('file://', FileAdapter())
        res = session.get(target_url, headers={'User-Agent': self.USER_AGENT})
        with open(target_url.replace('file://', ''), mode='r', encoding='utf-8') as file:
            return BeautifulSoup(file, 'html.parser')

    # Override
    def _write_csv(self):
        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}の店舗情報のCSVを出力します')
        page = 1
        max_page = math.ceil(self.limit / 20)  # 1ページあたり20件
        shop_count = 1

        while page <= max_page:
            soup = self.__beautiful_soup_instance(self.uri, page)
            shop_elems = soup.select('article > div.style_title___HrjW > a.style_titleLink__oiHVJ')
            shop_urls = [shop_elems[i].get('href') for i in range(len(shop_elems))]
            if not shop_urls:
                break
            if shop_count == 1:
                with open(self.filename, 'w', encoding='utf-8', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(self.CSV_HEADER)

            for gn_url in shop_urls:
                row = []
                soup = self.__beautiful_soup_instance(gn_url)

                # 店舗名
                shop_name = soup.select_one('#info-name').get_text(strip=True).replace('\xa0', ' ')
                row.append(shop_name)
                print('DEBUG', datetime.now(self.TIMEZONE), f'{str(shop_count).rjust(len(str(self.limit)))}/{self.limit}', shop_name, gn_url)
                # 電話番号
                tel = soup.select_one('#info-phone > td > ul > li:nth-child(1) > span.number').get_text(strip=True)
                row.append(tel)
                # メールアドレス
                email = ''
                try:
                    email = soup.select_one('#info-table > table > tbody a[href^=mailto]').get('href').replace('mailto:', '')
                    row.append(email)
                except AttributeError:
                    pass
                # 住所
                address = soup.select_one('#info-table > table > tbody p.adr > span.region').get_text(strip=True)
                prefecture, city, street = CsvCreator.separate_address(address)
                row.append(prefecture)
                row.append(city)
                row.append(street)

                # 建物名
                building = ''
                elem = soup.select_one('#info-table > table > tbody p.adr > span.locality')
                if elem:
                    building = elem.get_text(strip=True)
                    row.append(building)

                # URL
                official_url = ''
                # 「お店のホームページ」リンクからURL取得を試みる
                try:
                    shop_url_elem = soup.select_one('#info-table > table > tbody a.url')
                    if shop_url_elem:
                        shop_url_json = shop_url_elem.get('data-o')
                        if shop_url_json:
                            shop_url_info = json.loads(shop_url_json)
                            # SSLエラーを検知するためhttps固定にする(shop_url_info['b']にschemaが定義されている)
                            official_url = f"https://{shop_url_info['a']}"
                            time.sleep(0.5)
                            requests.get(official_url, headers={'User-Agent': self.USER_AGENT}, timeout=self.timeout)
                except requests.exceptions.SSLError:
                    official_url = official_url.replace('https://', 'http://')
                except requests.exceptions.ConnectionError:
                    pass

                # 「お店のホームページ」リンクからURLを取得できなかった場合、「オフィシャルページ」アイコンからURL取得を試みる
                if not official_url:
                    try:
                        shop_url_elem = soup.select_one('#sv-site > li > a')
                        if shop_url_elem:
                            official_url = shop_url_elem.get('href')
                            time.sleep(0.5)
                            requests.get(official_url, headers={'User-Agent': self.USER_AGENT}, timeout=self.timeout)
                    except requests.exceptions.SSLError:
                        official_url = official_url.replace('https://', 'http://')
                    except requests.exceptions.ConnectionError:
                        pass

                row.append(official_url)
                row.append(str(official_url.startswith('https')))
                with open(self.filename, 'a', encoding='utf-8', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(row)
                if shop_count >= self.limit:
                    print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}の店舗情報のCSVを出力しました')
                    return
                shop_count += 1

            page += 1
            time.sleep(3)

        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}の店舗情報のCSVを出力しました')

    # Override
    def _tearDown(self):
        if os.path.isdir('static/html'):
            shutil.rmtree('static/html')


class SeleniumCsvCreator(CsvCreator):
    """CsvCreator for selenium."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.driver = None
        self.wait = None

    # Override
    def _setUp(self):
        service = Service(executable_path='/usr/bin/chromedriver')
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(driver=self.driver, timeout=self.timeout)

        if os.path.isfile(self.filename):
            os.remove(self.filename)
        if self.uri.startswith('file:///opt/python/static/html/'):
            shutil.unpack_archive('static/html.zip', 'static/html')

    # Override
    def _write_csv(self):
        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}の店舗情報のCSVを出力します')

        page = 1
        max_page = math.ceil(self.limit / 20)  # 1ページあたり20件
        shop_count = 1

        self.driver.get(self.uri)
        while page <= max_page:
            url_selector = 'article > div.style_title___HrjW > a.style_titleLink__oiHVJ'
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, url_selector)))
            shop_elems = self.driver.find_elements(By.CSS_SELECTOR, url_selector)
            shop_urls = [shop_elems[i].get_attribute('href') for i in range(len(shop_elems))]
            if not shop_urls:
                break
            if shop_count == 1:
                with open(self.filename, 'w', encoding='utf-8', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(self.CSV_HEADER)

            for gn_url in shop_urls:
                row = []
                has_error = True
                for i in range(self.retry):
                    try:
                        # 新しいタブでアクセス
                        self.driver.switch_to.new_window('tab')
                        self.driver.switch_to.window(self.driver.window_handles[1])
                        self.driver.get(gn_url)
                        has_error = False
                        break
                    except TimeoutException:
                        print('WARN ', datetime.now(self.TIMEZONE), '     ', f'アクセス時にタイムアウトになりました({i + 1}回目)', gn_url)
                        self.driver.close()
                        self.driver.switch_to.window(self.driver.window_handles[0])
                        time.sleep(3)
                if has_error:
                    print('ERROR', datetime.now(self.TIMEZONE), '     ', 'アクセスできませんでした', gn_url)
                    sys.exit(0)

                # 店舗名
                shop_name = self.__find_shop_name()
                row.append(shop_name)
                print('DEBUG', datetime.now(self.TIMEZONE), f'{str(shop_count).rjust(len(str(self.limit)))}/{self.limit}', shop_name, gn_url)
                # 電話番号
                tel = self.__find_shop_tel()
                row.append(tel)
                # メールアドレス
                email = self.__find_shop_email()
                row.append(email)
                # 住所
                address = self.__find_shop_address()
                prefecture, city, street = CsvCreator.separate_address(address)
                row.append(prefecture)
                row.append(city)
                row.append(street)
                # 建物名
                building = self.__find_shop_building()
                row.append(building)
                # URL
                official_url = self.__find_shop_official_url()
                row.append(official_url)
                row.append(str(official_url.startswith('https')))
                self.driver.close()
                self.driver.switch_to.window(self.driver.window_handles[0])
                with open(self.filename, 'a', encoding='utf-8', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(row)
                if shop_count >= self.limit:
                    print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}の店舗情報のCSVを出力しました')
                    return
                shop_count += 1

            next_page_link_selector = '#__next > div > div.layout_body__LvaRc > main > div.style_pageNation__AZy1A > nav > ul > li:nth-last-child(2) > a'
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, next_page_link_selector)))
            next_page_link = self.driver.find_element(By.CSS_SELECTOR, next_page_link_selector)
            next_page_link.click()
            page += 1
            time.sleep(3)

        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}の店舗情報のCSVを出力しました')

    def __find_shop_name(self):
        shop_name_id = 'info-name'
        self.wait.until(EC.visibility_of_element_located((By.ID, shop_name_id)))
        elem = self.driver.find_element(By.ID, shop_name_id)
        return elem.text

    def __find_shop_tel(self):
        tel_selector = '#info-phone span.number'
        self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, tel_selector)))
        elem = self.driver.find_element(By.CSS_SELECTOR, tel_selector)
        return elem.text

    def __find_shop_email(self):
        elems = self.driver.find_elements(By.CSS_SELECTOR, '#info-table > table > tbody a[href^=mailto]')
        return elems[0].get_attribute('href').replace('mailto:', '') if elems else ''

    def __find_shop_address(self):
        return self.driver.find_element(By.CSS_SELECTOR, '#info-table > table > tbody p.adr > span.region').text

    def __find_shop_building(self):
        elems = self.driver.find_elements(By.CSS_SELECTOR, '#info-table > table > tbody p.adr > span.locality')
        return elems[0].text if elems else ''

    def __find_shop_official_url(self):
        official_url = ''
        # 「お店のホームページ」からURLを取得する
        url_selector = '#info-table > table > tbody a.url'
        elems = self.driver.find_elements(By.CSS_SELECTOR, url_selector)
        if elems:
            # 動的にhref属性が生成されるまで待機
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'{url_selector}:first-child[href^="http"]')))
            for k in range(self.retry):
                try:
                    # 別タブで開かれる
                    elems[0].click()
                    self.wait.until(EC.number_of_windows_to_be(3))
                    self.driver.switch_to.window(self.driver.window_handles[2])
                    official_url = self.driver.current_url
                    self.driver.close()
                    self.driver.switch_to.window(self.driver.window_handles[1])
                    break
                except TimeoutException:
                    print('WARN ', datetime.now(self.TIMEZONE), '     ', f'お店のホームページから店舗URLを取得できませんでした({k + 1}回目)')
                    time.sleep(3)

        # 「お店のホームページ」リンクからURLを取得できなかった場合、「オフィシャルページ」アイコンからURL取得を試みる
        if not official_url:
            elems = self.driver.find_elements(By.CSS_SELECTOR, '#sv-site > li > a')
            if elems:
                for l in range(self.retry):
                    try:
                        # 別タブで開かれる
                        elems[0].click()
                        self.wait.until(EC.number_of_windows_to_be(3))
                        self.driver.switch_to.window(self.driver.window_handles[2])
                        official_url = self.driver.current_url
                        self.driver.close()
                        self.driver.switch_to.window(self.driver.window_handles[1])
                        break
                    except TimeoutException:
                        print('WARN ', datetime.now(self.TIMEZONE), '     ', f'オフィシャルページから店舗URLを取得できませんでした({l + 1}回目)')
                        time.sleep(3)

        return official_url

    # Override
    def _tearDown(self):
        if os.path.isdir('static/html'):
            shutil.rmtree('static/html')

        self.driver.close()
        self.driver.quit()
