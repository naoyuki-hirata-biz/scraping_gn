import math
import time
import os
import re
import argparse
import pandas as pd
from datetime import datetime, timedelta, timezone
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

JST = timezone(timedelta(hours=+9), 'JST')

def get_args():
    parser = argparse.ArgumentParser(description='Usage')
    parser.add_argument('--filename', help='output csv filename (default: results_by_selenium.csv)', type=str)
    parser.add_argument('--uri', help='gnavi url (default: static files)', type=str)
    parser.add_argument('--shops', help='Maximum number of shops acquired (default: 50)', type=int)
    parser.add_argument('--timeout', help='Timeout time to find the element (seconds) (default: 90)', type=int)
    parser.add_argument('--retry', help='Number of retries (default: 3)', type=int)

    args = parser.parse_args()
    args.filename = args.filename or 'results_by_selenium.csv'
    args.uri = args.uri or 'file:///opt/python/static/gnavi_list_01.html'
    args.shops = args.shops or 50
    args.timeout = args.timeout or 90
    args.retry = args.retry or 3
    return vars(args)

def get_shop_urls(driver, **kwargs):
    urls = []
    page = 1
    max_page = math.ceil(kwargs['shops'] / 20)  # 1ページあたり20件

    wait = WebDriverWait(driver=driver, timeout=90)
    driver.get(kwargs['uri'])
    while page <= max_page:
        url_selector = 'article > div.style_title___HrjW > a.style_titleLink__oiHVJ'
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, url_selector)))
        elems = driver.find_elements(By.CSS_SELECTOR, url_selector)
        [urls.append(elems[i].get_attribute('href')) for i in range(len(elems))]
        if len(urls) >= kwargs['shops']:
            break

        next_page_link_selector = '#__next > div > div.layout_body__LvaRc > main > div.style_pageNation__AZy1A > nav > ul > li:nth-last-child(2) > a'
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, next_page_link_selector)))
        next_page_link = driver.find_element(By.CSS_SELECTOR, next_page_link_selector)
        next_page_link.click()
        page += 1
        time.sleep(3)

    return urls[:kwargs['shops']]

def get_shop_details(driver, target_urls, **kwargs):
    rows = []
    wait = WebDriverWait(driver=driver, timeout=kwargs['timeout'])
    limit = len(target_urls)
    for i in range(limit):
        row = []
        target_url = target_urls[i]
        has_error = True
        for j in range(kwargs['retry']):
          try:
            driver.get(target_url)
            has_error = False
            break
          except TimeoutException:
              print('WARN ', datetime.now(JST), '     ', f'アクセス時にタイムアウトになりました({j + 1}回目)', target_url)
              time.sleep(3)
        if has_error:
            print('ERROR', datetime.now(JST), '     ', 'アクセスできませんでした', target_url)
            exit()

        # 店舗名
        shop_name_id = 'info-name'
        wait.until(EC.visibility_of_element_located((By.ID, shop_name_id)))
        elem = driver.find_element(By.ID, shop_name_id)
        shop_name = elem.text
        row.append(shop_name)
        print('DEBUG', datetime.now(JST), f'{str(i + 1).rjust(len(str(limit)))}/{limit}', shop_name, target_url)
        # 電話番号
        tel_selector = '#info-phone span.number'
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, tel_selector)))
        elem = driver.find_element(By.CSS_SELECTOR, tel_selector)
        tel = elem.text
        row.append(tel)
        # メールアドレス
        email = ''
        elems = driver.find_elements(By.CSS_SELECTOR, '#info-table > table > tbody a[href^=mailto]')

        if len(elems) > 0:
            email = elems[0].get_attribute('href').replace('mailto:', '')
        row.append(email)
        # 住所
        address = driver.find_element(By.CSS_SELECTOR, '#info-table > table > tbody p.adr > span.region').text
        pattern = r'(東京都|北海道|(?:京都|大阪)府|.{2,3}県)?(.+?)(\d.*)'
        match = re.match(pattern, address)
        # 都道府県
        row.append(match.group(1))
        # 市区町村
        row.append(match.group(2))
        # 番地
        row.append(match.group(3))
        # 建物名
        building = ''
        elems = driver.find_elements(By.CSS_SELECTOR, '#info-table > table > tbody p.adr > span.locality')
        if elems:
            building = elems[0].text
        row.append(building)
        # URL, SSL
        url = ''
        ssl = ''
        ## 「お店のホームページ」からURLを取得する
        url_selector = '#info-table > table > tbody a.url'
        elems = driver.find_elements(By.CSS_SELECTOR, url_selector)
        if elems:
            # 動的にhref属性が生成されるまで待機
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'{url_selector}:first-child[href^="http"]')))
            for k in range(kwargs['retry']):
                try:
                    # 別タブで開かれる
                    elems[0].click()
                    wait.until(EC.number_of_windows_to_be(2))
                    handles = driver.window_handles
                    driver.switch_to.window(handles[1])
                    url = driver.current_url
                    if url.startswith('https'):
                        ssl = 'TRUE'
                    else:
                        ssl = 'FALSE'
                    driver.close()
                    driver.switch_to.window(handles[0])
                    break
                except TimeoutException:
                    print('WARN ', datetime.now(JST), '     ', f'{shop_name}のお店のホームページから店舗URLを取得できませんでした({k + 1}回目)')
                    time.sleep(3)

        ## 「お店のホームページ」リンクからURLを取得できなかった場合、「オフィシャルページ」アイコンからURL取得を試みる
        if url == '':
            elems = driver.find_elements(By.CSS_SELECTOR, '#sv-site > li > a')
            if len(elems) > 0:
                for l in range(kwargs['retry']):
                    try:
                        # 別タブで開かれる
                        elems[0].click()
                        wait.until(EC.number_of_windows_to_be(2))
                        handles = driver.window_handles
                        driver.switch_to.window(handles[1])
                        url = driver.current_url
                        if url.startswith('https'):
                            ssl = 'TRUE'
                        else:
                            ssl = 'FALSE'
                        driver.close()
                        driver.switch_to.window(handles[0])
                        break
                    except TimeoutException:
                        print('WARN ', datetime.now(JST), '     ', f'{shop_name}のオフィシャルページから店舗URLを取得できませんでした({l + 1}回目)')
                        time.sleep(3)

        row.append(url)
        row.append(ssl)
        rows.append(row)

    return pd.DataFrame(rows, columns=['店舗名', '電話番号', 'メールアドレス', '都道府県', '市区町村', '番地', '建物名', 'URL', 'SSL'])

# https://r.gnavi.co.jp/area/aream2115/kods00066/rs/?bdgMax=7000&character=KODS00143&sort=HIGH
def main():
    args = get_args()

    # 初期化
    if (os.path.isfile(args['filename'])):
        os.remove(args['filename'])

    service = Service(executable_path='/usr/bin/chromedriver')
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=service, options=options)

    # 一覧の店舗詳細URLを取得
    print('INFO ', datetime.now(JST), f"検索結果の上位{args['shops']}件のURLを取得します")
    shop_urls = get_shop_urls(driver, **args)
    print('INFO ', datetime.now(JST), f"検索結果の上位{args['shops']}件のURLを取得しました")

    print('INFO ', datetime.now(JST), '店舗詳細を取得します')
    shop_details = get_shop_details(driver, shop_urls, **args)
    print('INFO ', datetime.now(JST), '店舗詳細を取得しました')

    print('INFO ', datetime.now(JST), 'CSVファイルを出力します')
    shop_details.to_csv(args['filename'], encoding="utf-8_sig", index=False)
    print('INFO ', datetime.now(JST), 'CSVファイルを出力しました')

    driver.close()
    driver.quit()

# ==============================
# メイン処理
# ==============================
main()
