import pandas as pd

df = pd.read_excel('czasy_stref_wynik.xlsx', sheet_name='Dane_surowe')
print('Wczytano:', len(df))

df = df.rename(columns={'strefa': 'strefa_docelowa', 'wejscie': 'dt', 'wyjscie': 'dt_exit'})
df['data'] = pd.to_datetime(df['data']).dt.tz_localize(None)

def hms_to_s(t):
    try:
        parts = str(t).split(':')
        return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
    except:
        return 0

df['czas_s'] = df['czas'].apply(hms_to_s)

# Buduj dt i dt_exit z daty + czasu HH:MM:SS (kolumna 'czas' to już czas trwania, nie godzina)
# dt i dt_exit są w Excelu jako datetime - weź tylko część czasową
df['dt']     = pd.to_datetime(df['dt'],     errors='coerce', utc=True).dt.tz_localize(None)
df['dt_exit']= pd.to_datetime(df['dt_exit'],errors='coerce', utc=True).dt.tz_localize(None)

# Jeśli dt jest puste - zrekonstruuj z daty
mask = df['dt'].isna()
df.loc[mask, 'dt']     = df.loc[mask, 'data']
df.loc[mask, 'dt_exit']= df.loc[mask, 'data']

df = df.drop(columns=['czas'])
df.to_parquet('czasy_calc.parquet', index=False)
print('OK — zapisano czasy_calc.parquet:', len(df), 'wierszy')
print('Kolumny:', df.columns.tolist())
print('Przykład dt:', df['dt'].head(3).tolist())