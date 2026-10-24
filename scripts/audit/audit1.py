import pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_columns',50); pd.set_option('display.max_colwidth',60)
for f in ['df_Uid_data_hack.csv','df_Fid_Uid_link_hack.csv','df_Uid_payment_hack.csv']:
    raw=open(f,'rb').read(3); print('==',f,'BOM' if raw==b'\xef\xbb\xbf' else 'noBOM')
    df=pd.read_csv(f,sep=';',dtype=str,keep_default_na=False)
    print(df.shape); print(df.columns.tolist())
    print(df.head(3).to_string())
    for c in df.columns:
        s=df[c]; print(f"  {c}: nunique={s.nunique()} empty={(s=='').sum()} sample={s.unique()[:5].tolist()}")
    print('  full-dup rows:',df.duplicated().sum())
