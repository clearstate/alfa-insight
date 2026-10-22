import pandas as pd
pd.set_option('display.width',250)
u=pd.read_csv('df_Uid_data_hack.csv',sep=';',dtype=str,keep_default_na=False); u['rev']=u.REVENUE_COMPANY.astype(float)
f=pd.read_csv('df_Fid_Uid_link_hack.csv',sep=';',dtype=str,keep_default_na=False)
p=pd.read_csv('df_Uid_payment_hack.csv',sep=';',dtype={'BENEFICIARY':str,'PAYER':str})
ud=u.drop_duplicates('SYNTHETIC_U')
for c in ['г. Москва','г. Санкт-Петербург','г. Донецк']:
    print(c, u[u.CITY==c].REGION.value_counts().to_dict())
print('names multi-code examples:')
nc=u.groupby('MAINOKVED_NAME').MAINOKVED_CODE.unique(); print(nc[nc.str.len()>1].to_string())
gs=ud.groupby('GROUP_ID').agg(n=('SYNTHETIC_U','size'),rev=('rev','sum'),okved=('MAINOKVED_CODE',lambda s:s.str[:2].nunique()),regions=('REGION','nunique')).sort_values('n',ascending=False)
print(gs.head(8).to_string())
U=set(ud.SYNTHETIC_U); miss=f[~f.SYNTHETIC_U.isin(U)].SYNTHETIC_U
print('missing link U in payments:',miss.isin(set(p.PAYER)|set(p.BENEFICIARY)).mean().round(3))
sp=p[p.PAYER==p.BENEFICIARY]; print('self-pay amt share of total:',round(sp.PAY_AMT.sum()/p.PAY_AMT.sum(),3),' median amt',sp.PAY_AMT.median())
print('top payments:'); print(p.nlargest(5,'PAY_AMT').to_string())
d=p[p.duplicated(['PAYER','BENEFICIARY'],keep=False)].sort_values(['PAYER','BENEFICIARY']); print(d.head(6).to_string())
big=ud[ud.rev>=15e9]
print('big: LOA',big.CL_PRODUCT_LOA_MARK.value_counts().to_dict(),' FTS',big.FTS_FLAG.value_counts().to_dict(),' DEP',big.CL_PRODUCT_DEP_MARK.value_counts().to_dict(),' regions',big.REGION.value_counts().head(5).to_dict())
print('big FNS workers:',big.AMOUNT_WORKERS_FNS_GRADATION.value_counts().to_dict())
print('ECO empty x CL_TYPE:',u[u.ECO_MARK_LABEL==''].CL_TYPE.value_counts().to_dict())
