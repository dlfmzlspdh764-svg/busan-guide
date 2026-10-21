import os,urllib.request,urllib.parse
k=os.environ['DATA_GO_KR_KEY'];B='https://apis.data.go.kr/6260000/HouseTradePriceService'
for op in ['','getHouseTradePriceInfo','getHouseTradePrice','getHouseTradePriceList','getHouseTradePriceInfoList','getHouseTradeInfo']:
  u=f"{B}/{op}?serviceKey={urllib.parse.quote(k)}&pageNo=1&numOfRows=3&resultType=json"
  try:
    r=urllib.request.urlopen(u,timeout=30);s=r.status;b=r.read().decode('utf-8','replace')
  except urllib.error.HTTPError as e: s=e.code;b=e.read().decode('utf-8','replace')
  except Exception as e: s='ERR';b=str(e)
  print('==',op or '(root)',s,b[:700].replace(k,'***'))
