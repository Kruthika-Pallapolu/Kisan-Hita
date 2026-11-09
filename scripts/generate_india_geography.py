#!/usr/bin/env python3
"""Fetch a dated LGD snapshot and generate local seven-script place labels.

Requires Python's standard library, macOS Swift/Foundation (ICU transliteration),
and a trusted CA bundle. Runtime app use is fully offline.
"""
from __future__ import annotations
import json, os, re, ssl, subprocess, urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'frontend/src/data/india-geography.json'
BASE = 'https://lgdirectory.gov.in/webservices/lgdws'
LANGS = ['en', 'te', 'hi', 'ta', 'kn', 'ml', 'mr']
SCRIPT = {'te': r'[\u0c00-\u0c7f]', 'hi': r'[\u0900-\u097f]', 'mr': r'[\u0900-\u097f]', 'ta': r'[\u0b80-\u0bff]', 'kn': r'[\u0c80-\u0cff]', 'ml': r'[\u0d00-\u0d7f]'}

# Common, recognizable spellings for pilot districts; English names and LGD codes remain canonical.
OVERRIDES = {
 'Nellore': {'te':'నెల్లూరు','hi':'नेल्लोर','ta':'நெல்லூர்','kn':'ನೆಲ್ಲೂರು','ml':'നെല്ലൂർ','mr':'नेल्लोर'},
 'Guntur': {'te':'గుంటూరు','hi':'गुंटूर','ta':'குண்டூர்','kn':'ಗುಂಟೂರು','ml':'ഗുണ്ടൂർ','mr':'गुंटूर'},
 'Warangal': {'te':'వరంగల్','hi':'वारंगल','ta':'வாரங்கல்','kn':'ವಾರಂಗಲ್','ml':'വാറങ്കൽ','mr':'वारंगल'},
 'Nizamabad': {'te':'నిజామాబాద్','hi':'निज़ामाबाद','ta':'நிஜாமாபாத்','kn':'ನಿಜಾಮಾಬಾದ್','ml':'നിസാമാബാദ്','mr':'निजामाबाद'},
 'Pune': {'te':'పుణె','hi':'पुणे','ta':'புனே','kn':'ಪುಣೆ','ml':'പൂനെ','mr':'पुणे'},
 'Belagavi': {'te':'బెలగావి','hi':'ಬೆಳಗಾವಿ','ta':'பெலகாவி','kn':'ಬೆಳಗಾವಿ','ml':'ബെളഗാവി','mr':'बेळगावी'},
 'Coimbatore': {'te':'కోయంబత్తూరు','hi':'कोयंबटूर','ta':'கோயம்புத்தூர்','kn':'ಕೊಯಮತ್ತೂರು','ml':'കോയമ്പത്തൂർ','mr':'कोयंबतूर'},
 'Palakkad': {'te':'పాలక్కాడ్','hi':'पलक्कड़','ta':'பாலக்காடு','kn':'ಪಾಲಕ್ಕಾಡ್','ml':'പാലക്കാട്','mr':'पालक्काड'},
}

def get_json(url):
    req=urllib.request.Request(url, data=b'', headers={'Content-Type':'application/json'}, method='POST')
    cafile=os.environ.get('SSL_CERT_FILE')
    if not cafile:
        try:
            import certifi
            cafile=certifi.where()
        except ImportError:
            cafile=ssl.get_default_verify_paths().cafile
    with urllib.request.urlopen(req, context=ssl.create_default_context(cafile=cafile), timeout=40) as r:
        return json.load(r)

def canonical(name):
    aliases={'Jammu And Kashmir':'Jammu and Kashmir', 'Andaman And Nicobar Islands':'Andaman and Nicobar Islands',
      'The Dadra And Nagar Haveli And Daman And Diu':'Dadra and Nagar Haveli and Daman and Diu',
      'Dadra And Nagar Haveli And Daman And Diu':'Dadra and Nagar Haveli and Daman and Diu'}
    if name in aliases: return aliases[name]
    return ' '.join(w if w.lower() in {'and','of','the'} else w.capitalize() for w in name.split())

def main():
    states=get_json(BASE+'/stateList')
    raw=[]
    for s in states:
        ds=get_json(f"{BASE}/districtList?stateCode={s['stateCode']}")
        sn=canonical(s['stateNameEnglish'])
        raw.append({'lgdCode':str(s['stateCode']), 'name':sn, 'local':s.get('stateNameLocal',''), 'districts':[
          {'lgdCode':str(d['districtCode']), 'stateCode':str(s['stateCode']), 'name':canonical(d['districtNameEnglish']), 'local':d.get('districtNameLocal','')} for d in ds]})
    # Swift/Foundation uses macOS ICU transliteration without third-party dependencies.
    swift = r'''import Foundation
let input = FileHandle.standardInput.readDataToEndOfFile()
let obj = try JSONSerialization.jsonObject(with: input) as! [[String:Any]]
let transforms:[String:String] = ["te":"Latin-Telugu", "hi":"Latin-Devanagari", "mr":"Latin-Devanagari", "ta":"Latin-Tamil", "kn":"Latin-Kannada", "ml":"Latin-Malayalam"]
func x(_ text:String, _ lang:String)->String { let t=StringTransform(transforms[lang]!); return text.applyingTransform(t, reverse:false) ?? text }
func names(_ text:String)->[String:String] { var n:[String:String] = ["en": text]; for lang in transforms.keys { n[lang]=x(text,lang) }; return n }
let result = obj.map { state -> [String:Any] in
 var s=state; s["names"]=names(state["name"] as! String)
 let ds=(state["districts"] as! [[String:Any]]).map { d -> [String:Any] in var item=d; item["names"]=names(d["name"] as! String); return item }
 s["districts"]=ds; return s
}
let data=try JSONSerialization.data(withJSONObject: result, options:[.prettyPrinted,.sortedKeys,.withoutEscapingSlashes]); FileHandle.standardOutput.write(data)
'''
    swift_result=subprocess.run(['swift','-module-cache-path','/private/tmp/kisan-swift-cache','-e',swift],input=json.dumps(raw,ensure_ascii=False).encode(),capture_output=True,check=False)
    if swift_result.returncode: raise RuntimeError(swift_result.stderr.decode())
    generated=json.loads(swift_result.stdout)
    union_territories={'Andaman and Nicobar Islands','Chandigarh','Dadra and Nagar Haveli and Daman and Diu','Delhi','Jammu and Kashmir','Ladakh','Lakshadweep','Puducherry'}
    for si, state in enumerate(generated):
        source=raw[si]
        state['type']='union_territory' if state['name'] in union_territories else 'state'
        for lang,pattern in SCRIPT.items():
            if source['local'] and re.search(pattern,source['local']): state['names'][lang]=source['local']
        for di,d in enumerate(state['districts']):
            original=source['districts'][di]
            for lang,pattern in SCRIPT.items():
                if original['local'] and re.search(pattern,original['local']): d['names'][lang]=original['local']
            d['fallbackLanguages']=[lang for lang in LANGS if not d['names'].get(lang)]
            for lang in d['fallbackLanguages']: d['names'][lang]=d['name']
            d.pop('local',None)
        state['fallbackLanguages']=[]
        state.pop('local',None)
    # Apply curated spellings by canonical district name.
    for s in generated:
        for d in s['districts']:
            if d['name'] in OVERRIDES: d['names'].update(OVERRIDES[d['name']])
    doc={'source':'Local Government Directory (LGD), Ministry of Panchayati Raj, India; official stateList and districtList services',
      'sourceUrl':'https://lgdirectory.gov.in/', 'retrievedOn':date.today().isoformat(), 'stateCount':len(generated),
          'districtCount':sum(len(s['districts']) for s in generated), 'languages':LANGS,
      'stateCountSplit':{'states':28,'unionTerritories':8}, 'localizationNote':'Canonical English names and LGD codes are preserved. Official LGD local names are used where present in the matching script; other proper names use offline macOS ICU transliteration, not semantic translation. Transliteration and local spellings require fluent-speaker review. English fallback is explicit per record when no label is available.',
      'states':generated}
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    print(f"Wrote {doc['stateCount']} states/UTs and {doc['districtCount']} districts to {OUT}")
if __name__=='__main__': main()
