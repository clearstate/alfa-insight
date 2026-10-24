import sys, yaml, pandas as pd
sys.path.insert(0,'.')
# Запуск: python scripts/build_industry_terms.py <папка с CSV кейса>
DATA=sys.argv[1] if len(sys.argv)>1 else '/home/claude/data'
from services.company_profile.okved import okved_levels
E=[ # id, terms, prefixes, industry_rule, ambiguous_terms, note
("oil_gas",["нефть","нефтян","нефтегаз","нефтепродукт","добыча газа","газодобыч","топливо"],["06","09.1","19.2","46.71","49.5"],"mining_energy",["газ"],"«газ» сам по себе неоднозначен (газ для ЖКХ, промышленные газы 20.11)"),
("coal",["уголь","угольн"],["05","46.71.1"],"mining_energy",[],None),
("metals_mining",["металлург","сталь","стальн","металлопрокат","цветные металлы","руда","рудн"],["07","24","46.72"],"metals",[],None),
("metal_products",["металлоконструкц","металлоизделия"],["25"],"metals",[],None),
("precious_metals",["золото","золотодобыч","драгметалл","драгоценные металлы"],["07.29.4","24.41","32.12"],"precious_metals",[],"Опт драгметаллами отдельного проверенного кода в данных нет: 46.72.2 — металлы в первичных формах"),
("chemicals",["химическ","химпром","удобрени"],["20"],"chemicals_pharma",[],None),
("pharma",["фармацевт","фарма","лекарств"],["21","46.46"],"chemicals_pharma",[],None),
("construction",["строительств","стройк","застройщик","девелопер","девелопмент","инфраструктурн"],["41","42","43"],"construction_real_estate",[],None),
("building_materials",["стройматериал","цемент","кирпич","бетон"],["23"],None,[],None),
("real_estate",["недвижимост","коммерческая недвижимость","аренда офис"],["68"],"construction_real_estate",["аренда"],"«аренда» встречается и в лизинге, и в аренде оборудования"),
("retail",["ритейл","ретейл","розничная торговля","розничные сети","продуктовый ритейл"],["47"],"retail_trade",["магазин"],None),
("wholesale",["оптовая торговля","оптовик","дистрибуц","дистрибьютор"],["46"],"wholesale_trade",[],None),
("food_service",["общепит","ресторан","кафе","доставка еды"],["56"],"hospitality_food_service",[],None),
("hospitality_tourism",["туризм","туристическ","гостиниц","отел","туроператор","турагент"],["55","79"],"hospitality_food_service",[],None),
("auto",["автопром","автомобил","автодилер","авторынок"],["29","45"],"auto",[],None),
("auto_parts",["автозапчаст","автокомпонент","автомобильн комплектующ"],["45.3","29.3"],"auto",["запчаст","комплектующ"],"«запчасти» и «комплектующие» без указания на автомобили бывают и для станков, и для самолётов — отрасль не задают"),
("road_freight_logistics",["грузоперевоз","автоперевоз","грузовой транспорт","логистик"],["49.4","52.1","52.24","52.29","53"],"transport_logistics",["перевозк"],"«перевозки» без уточнения могут быть пассажирскими"),
("rail",["железнодорож","ж/д перевоз","грузовые вагон"],["49.1","49.2"],"transport_logistics",[],None),
("shipping",["морск","судоходств","порт","контейнерн"],["50","52.22"],"transport_logistics",["порт"],"«порт» встречается в составных словах (импорт, экспорт): матчить только как отдельное слово"),
("aviation",["авиаперевоз","авиакомпани","авиаци"],["51"],"transport_logistics",[],None),
("agro",["сельское хозяйство","сельхоз","агро","апк","урожай","зерн"],["01","03"],"agro_food",[],None),
("food_industry",["пищев","мясн","молочн","переработка продукт"],["10"],"agro_food",[],None),
("beverages",["алкогол","пиво","напитк"],["11","46.34"],"agro_food",[],None),
("power",["электроэнерг","энергетик","генерац","электростанц","энергосбыт"],["35.1"],"mining_energy",[],None),
("utilities",["жкх","водоснабжен","водоотведен","вывоз мусора","отходы","теплоснабжен"],["35.3","36","37","38","39"],None,[],None),
("telecom",["телеком","оператор связи","мобильная связь","связи"],["61"],"it_telecom",["связи"],"«связи» часто в значении «в связи с»: только как часть фразы «оператор(ы) связи»"),
("it",["ит-","it-","айти","программное обеспечение","разработк по","софт","облачн"],["62","63"],"it_telecom",[],None),
("media",["сми","медиа","издательств"],["58","59","60"],None,[],None),
("finance",["страхов","лизингов","финансовые организации","микрофинанс"],["64","65","66"],"finance",["банк"],"«банк» почти всегда про сам Альфа-Банк или ЦБ: не использовать как отраслевой маркер. В 64 входят и холдинговые компании (64.20)"),
("machinery",["машиностроен","станкостроен","промышленное оборудован"],["28"],None,[],None),
("electronics",["электроник","микроэлектрон","полупроводник"],["26"],None,[],None),
("electrical",["электротехн","кабельн"],["27"],None,[],None),
("transport_equipment",["судостроен","авиастроен","вагоностроен"],["30"],None,[],None),
("forestry_paper",["лесопром","древесин","пиломатериал","целлюлоз","бумаг","картон"],["02","16","17"],None,[],None),
("healthcare",["здравоохранен","медицинск","клиник"],["86"],None,[],None),
("education",["образовани"],["85"],None,[],None),
("engineering_services",["проектирован","инжиниринг","изыскани"],["71"],"professional_services",[],None),
]
u=pd.read_csv(DATA+'/df_Uid_data_hack.csv',sep=';',dtype=str,keep_default_na=False)
c=u.drop_duplicates('MAINOKVED_CODE')[['MAINOKVED_CODE','MAINOKVED_NAME']].sort_values('MAINOKVED_CODE')
c['lv']=c.MAINOKVED_CODE.map(lambda x: okved_levels(x) or ())
cnt=u.MAINOKVED_CODE.value_counts()
out=[]
for i,terms,prefs,rule,amb,note in E:
    pp=[]
    for p in prefs:
        assert okved_levels(p), p
        m=c[c.lv.map(lambda l, p=p:p in l)]
        if len(m):
            ex=m.iloc[0]; pp.append({"prefix":p,"verified":"data","example_okved":f"{ex.MAINOKVED_CODE} {ex.MAINOKVED_NAME}","companies_in_data":int(cnt[m.MAINOKVED_CODE].sum())})
        else:
            pp.append({"prefix":p,"verified":"classifier","example_okved":None,"companies_in_data":0})
    d={"id":i,"terms":terms,"okved_prefixes":pp,"industry_rule":rule}
    if amb: d["ambiguous_terms"]=amb
    if note: d["note"]=note
    out.append(d)
hdr='''# Словарь «отраслевой термин -> префиксы ОКВЭД2». Владелец словаря — участник 1, файл в contracts/ (ревью участников 2, 4, 6).
# Назначение: участник 2 размечает news_item.industries, участник 4 сопоставляет их с profile.industry.okved_levels
# и с отраслями контрагентов (profile.sensitivity_factors[supply_chain_industries]).
#
# terms — нижний регистр, основы слов: совпадение = вхождение в лемматизированный текст (лемматизация — у участника 2).
# ambiguous_terms — сами по себе отрасль НЕ задают, только вместе с другим термином записи.
# verified: data       — префикс встречается в df_Uid_data_hack.csv, смысл сверен по MAINOKVED_NAME (example_okved);
#           classifier — по ОКВЭД2 (ОК 029-2014), в данных кейса не встречается, смысл НЕ сверен с данными.
# industry_rule — id правила в services/company_profile/config/feature_rules.yaml (темы профиля), null если правила нет.
# Сгенерировано скриптом сверки с данными кейса; правки — PR с ревью участника 1.
'''
doc={"version":1,"format":"okved_prefix","entries":out}
open('contracts/industry_terms.yaml','w').write(hdr+yaml.safe_dump(doc,allow_unicode=True,sort_keys=False,width=120))
v=sum(p['verified']=='data' for e in out for p in e['okved_prefixes']); t=sum(len(e['okved_prefixes']) for e in out)
print(len(out),'entries',t,'prefixes',v,'verified in data')
print([ (e['id'],p['prefix']) for e in out for p in e['okved_prefixes'] if p['verified']=='classifier'])
