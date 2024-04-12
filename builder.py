from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests_file import FileAdapter
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@dataclass
class Shop:
    name: str = ''
    tel: str = ''
    email: str = ''
    prefecture: str = ''
    city: str = ''
    street: str = ''
    building: str = ''
    gn_url: str = ''
    official_url: str = ''

    def parse_address(self, address):
        pattern = r'(東京都|北海道|(?:京都|大阪)府|.{2,3}県)?(.+?)(\d.*)'
        match = re.match(pattern, address)
        self.prefecture = match.group(1)
        self.city = match.group(2)
        self.street = match.group(3)

    def secure(self):
        return self.official_url.startswith('https')

    def to_list(self):
        return [self.name, self.tel, self.email, self.prefecture, self.city, self.street, self.building, self.official_url, self.secure()]

class CsvBuilder:
    TIMEZONE = timezone(timedelta(hours=+9), 'JST')

    def __init__(self, **kwargs):
        self.shops = []

        self.filename = kwargs['filename']
        self.uri = kwargs['uri']
        self.limit = kwargs['shops']
        self.timeout = kwargs['timeout']
        self.retry = kwargs['retry']

    @abstractmethod
    def build(self) -> CsvBuilder:
        pass

    def write_csv(self) -> CsvBuilder:
        print('INFO ', datetime.now(self.TIMEZONE), 'CSVファイルを出力します')
        rows = [shop.to_list() for shop in self.shops]
        df = pd.DataFrame(rows, columns=['店舗名', '電話番号', 'メールアドレス', '都道府県', '市区町村', '番地', '建物名', 'URL', 'SSL'])
        df.to_csv(self.filename, encoding="utf-8_sig", index=False)
        print('INFO ', datetime.now(self.TIMEZONE), 'CSVファイルを出力しました')
        return self

class CsvBuilderFactory:
    @staticmethod
    def create_csv_builder(**kwargs):
        lib = kwargs['lib']
        if lib == 'requests':
            return RequestsCsvBuilder(**kwargs)
        elif lib == 'selenium':
            return SeleniumCsvBuilder(**kwargs)
        else:
            raise ValueError(f'Unknown type: {lib}')

class RequestsCsvBuilder(CsvBuilder):
    USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # Override
    def build(self) -> CsvBuilder:
        self.__setUp()

        self.__set_gn_url_of_shops()
        self.__set_shop_details()

        self.__tearDown()
        return self

    def __setUp(self):
        if (os.path.isfile(self.filename)):
            os.remove(self.filename)
        if (self.uri.startswith('file:///opt/python/static/html/')):
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
            target_url =  url

        session.mount('file://', FileAdapter())
        res = session.get(target_url, headers={'User-Agent': self.USER_AGENT})
        f = open(target_url.replace('file://', ''), 'r')
        soup = BeautifulSoup(f, 'html.parser')
        f.close()
        return soup

    def __set_gn_url_of_shops(self):
        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}件のURLを取得します')
        page = 1
        max_page = math.ceil(self.limit / 20)  # 1ページあたり20件
        while page <= max_page:
            soup = self.__beautiful_soup_instance(self.uri, page)
            shop_elems = soup.select('article > div.style_title___HrjW > a.style_titleLink__oiHVJ')
            if not shop_elems:
                break
            for elem in shop_elems:
                self.shops.append(Shop(gn_url=elem.get('href')))
                if len(self.shops) >= self.limit:
                    print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}件のURLを取得しました')
                    return

            page += 1
            time.sleep(3)

        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}件のURLを取得しました')

    def __set_shop_details(self):
        print('INFO ', datetime.now(self.TIMEZONE), '店舗詳細を取得します')

        limit = len(self.shops)
        for i, shop in enumerate(self.shops):

            soup = self.__beautiful_soup_instance(shop.gn_url)
            # 店舗名
            shop.name = soup.select_one('#info-name').get_text(strip=True).replace(u'\xa0', u' ')
            print('DEBUG', datetime.now(self.TIMEZONE), f'{str(i + 1).rjust(len(str(limit)))}/{limit}', shop.name, shop.gn_url)
            # 電話番号
            shop.tel = soup.select_one('#info-phone > td > ul > li:nth-child(1) > span.number').get_text(strip=True)
            # メールアドレス
            try:
                shop.email = soup.select_one('#info-table > table > tbody a[href^=mailto]').get('href').replace('mailto:', '')
            except AttributeError:
                pass
            # 住所
            address = soup.select_one('#info-table > table > tbody p.adr > span.region').get_text(strip=True)
            shop.parse_address(address)
            # 建物名
            try:
                shop.building = soup.select_one('#info-table > table > tbody p.adr > span.locality').get_text(strip=True)
            except AttributeError:
                pass
            # URL
            ## 「お店のホームページ」リンクからURL取得を試みる
            try:
                shop_url_elem = soup.select_one('#info-table > table > tbody a.url')
                if shop_url_elem:
                    shop_url_json = shop_url_elem.get('data-o')
                    if shop_url_json:
                        shop_url_info = json.loads(shop_url_json)
                        # SSLエラーを検知するためhttps固定にする(shop_url_info['b']にschemaが定義されている)
                        shop.official_url = f"https://{shop_url_info['a']}"
                        time.sleep(0.5)
                        requests.get(shop.official_url, headers={'User-Agent': self.USER_AGENT})
            except requests.exceptions.SSLError:
                shop.official_url = shop.official_url.replace('https://', 'http://')
            except requests.exceptions.ConnectionError:
                pass

            ## 「お店のホームページ」リンクからURLを取得できなかった場合、「オフィシャルページ」アイコンからURL取得を試みる
            if not shop.official_url:
                try:
                    shop_url_elem = soup.select_one('#sv-site > li > a')
                    if shop_url_elem:
                        shop.official_url = shop_url_elem.get('href')
                        time.sleep(0.5)
                        requests.get(shop.official_url, headers={'User-Agent': self.USER_AGENT})
                except requests.exceptions.SSLError:
                    shop.official_url = shop.official_url.replace('https://', 'http://')
                except requests.exceptions.ConnectionError:
                    pass

            time.sleep(3)

        print('INFO ', datetime.now(self.TIMEZONE), '店舗詳細を取得しました')

    def __tearDown(self):
        if os.path.isdir('static/html'):
            shutil.rmtree('static/html')

class SeleniumCsvBuilder(CsvBuilder):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.driver = None
        self.wait = None

    # Override
    def build(self) -> CsvBuilder:
        self.__setUp()

        self.__set_gn_url_of_shops()
        self.__set_shop_details()

        self.__tearDown()
        return self

    def __setUp(self):
        service = Service(executable_path='/usr/bin/chromedriver')
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(driver=self.driver, timeout=self.timeout)

        if (os.path.isfile(self.filename)):
            os.remove(self.filename)
        if (self.uri.startswith('file:///opt/python/static/html/')):
            shutil.unpack_archive('static/html.zip', 'static/html')

    def __set_gn_url_of_shops(self):
        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}件のURLを取得します')

        page = 1
        max_page = math.ceil(self.limit / 20)  # 1ページあたり20件

        self.driver.get(self.uri)
        while page <= max_page:
            url_selector = 'article > div.style_title___HrjW > a.style_titleLink__oiHVJ'
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, url_selector)))
            elems = self.driver.find_elements(By.CSS_SELECTOR, url_selector)
            [self.shops.append(Shop(gn_url=elems[i].get_attribute('href'))) for i in range(len(elems))]
            if len(self.shops) >= self.limit:
                break

            next_page_link_selector = '#__next > div > div.layout_body__LvaRc > main > div.style_pageNation__AZy1A > nav > ul > li:nth-last-child(2) > a'
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, next_page_link_selector)))
            next_page_link = self.driver.find_element(By.CSS_SELECTOR, next_page_link_selector)
            next_page_link.click()
            page += 1
            time.sleep(3)

        self.shops = self.shops[:self.limit]
        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}件のURLを取得しました')

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
        ## 「お店のホームページ」からURLを取得する
        url_selector = '#info-table > table > tbody a.url'
        elems = self.driver.find_elements(By.CSS_SELECTOR, url_selector)
        if elems:
            # 動的にhref属性が生成されるまで待機
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'{url_selector}:first-child[href^="http"]')))
            for k in range(self.retry):
                try:
                    # 別タブで開かれる
                    elems[0].click()
                    self.wait.until(EC.number_of_windows_to_be(2))
                    handles = self.driver.window_handles
                    self.driver.switch_to.window(handles[1])
                    official_url = self.driver.current_url
                    self.driver.close()
                    self.driver.switch_to.window(handles[0])
                    break
                except TimeoutException:
                    print('WARN ', datetime.now(self.TIMEZONE), '     ', f'お店のホームページから店舗URLを取得できませんでした({k + 1}回目)')
                    time.sleep(3)

        ## 「お店のホームページ」リンクからURLを取得できなかった場合、「オフィシャルページ」アイコンからURL取得を試みる
        if not official_url:
            elems = self.driver.find_elements(By.CSS_SELECTOR, '#sv-site > li > a')
            if elems:
                for l in range(self.retry):
                    try:
                        # 別タブで開かれる
                        elems[0].click()
                        self.wait.until(EC.number_of_windows_to_be(2))
                        handles = self.driver.window_handles
                        self.driver.switch_to.window(handles[1])
                        official_url = self.driver.current_url
                        self.driver.close()
                        self.driver.switch_to.window(handles[0])
                        break
                    except TimeoutException:
                        print('WARN ', datetime.now(self.TIMEZONE), '     ', f'オフィシャルページから店舗URLを取得できませんでした({l + 1}回目)')
                        time.sleep(3)

        return official_url

    def __set_shop_details(self):
        print('INFO ', datetime.now(self.TIMEZONE), '店舗詳細を取得します')

        limit = len(self.shops)
        for i, shop in enumerate(self.shops):
            has_error = True
            for j in range(self.retry):
                try:
                    self.driver.get(shop.gn_url)
                    has_error = False
                    break
                except TimeoutException:
                    print('WARN ', datetime.now(self.TIMEZONE), '     ', f'アクセス時にタイムアウトになりました({j + 1}回目)', shop.gn_url)
                    time.sleep(3)
            if has_error:
                print('ERROR', datetime.now(self.TIMEZONE), '     ', 'アクセスできませんでした', shop.gn_url)
                exit()

            # 店舗名
            shop.name = self.__find_shop_name()
            print('DEBUG', datetime.now(self.TIMEZONE), f'{str(i + 1).rjust(len(str(limit)))}/{limit}', shop.name, shop.gn_url)
            # 電話番号
            shop.tel = self.__find_shop_tel()
            # メールアドレス
            shop.email = self.__find_shop_email()
            # 住所
            shop.parse_address(self.__find_shop_address())
            # 建物名
            shop.building = self.__find_shop_building()
            # URL
            shop.official_url = self.__find_shop_official_url()

        print('INFO ', datetime.now(self.TIMEZONE), '店舗詳細を取得しました')

    def __tearDown(self):
        if os.path.isdir('static/html'):
            shutil.rmtree('static/html')

        self.driver.close()
        self.driver.quit()
