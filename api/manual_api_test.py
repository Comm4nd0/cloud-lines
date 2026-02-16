import requests
import sys
from pprint import pprint
from json import loads, dumps

print(f"Domain: {sys.argv[1]}") # https://demo.cloud-lines.com
print(f"Username: {sys.argv[2]}") # myusername
print(f"Password: {sys.argv[3]}") # supersecretpassword

## Get the token
token_res = requests.post(url=f'{sys.argv[1]}/api/api-token-auth', data={'username': sys.argv[2], 'password': sys.argv[3]})
print(token_res.json())

## create header
headers = {'Content-Type': 'application/json', 'Authorization': f"token {token_res.json()['token']}"}

## get pedigrees

post_res = requests.get(url=f'{sys.argv[1]}/api/stud_advisor/80/', headers=headers)
pprint(post_res.json())
data = loads(post_res.text)
data["failed"] = True
data["failed_message"] = "It aint worked!"

post_res = requests.put(url=f'{sys.argv[1]}/api/stud_advisor/80/', data=dumps(data), headers=headers)
pprint(post_res.json())