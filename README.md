# scraping gn
[![Python Version](https://img.shields.io/badge/python-3.9-brightgreen.svg)](https://python.org)

```
usage: csv_export.py [-h] --uri URI [--lib {requests,selenium}] [--filename FILENAME] [--shops SHOPS] [--timeout TIMEOUT] [--retry RETRY]

Usage

optional arguments:
  -h, --help            show this help message and exit
  --uri URI             gnavi url (If using static files, specify 'file:///opt/python/static/html/gnavi_list_01.html')
  --lib {requests,selenium}
                        use requests or selenium library (default: selenium)
  --filename FILENAME   output csv filename (default: results.csv)
  --shops SHOPS         Maximum number of shops acquired (default: 50)
  --timeout TIMEOUT     Timeout time to find the element (seconds) (default: 90)
  --retry RETRY         Number of retries (default: 3)
  ```
