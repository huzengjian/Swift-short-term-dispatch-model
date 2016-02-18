input_path = "data\\tmp.csv"
output_path = "data\\cleanup.csv"
xlabel = "Cwz Sw1 head"
ylabel = "h/k"

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

data = pd.read_csv(path)
data['Cwz inflow'] = data['Cwz inflow'].str.replace(',', '')

data = data.convert_objects(convert_numeric=True)
data = data[np.isfinite(data[ylabel])]
data = data[np.isfinite(data["Cwz inflow"])]
data = data[data[ylabel] > 10]
data = data[data[ylabel] < 50]

data['elevation change'] = np.diff(pd.Series(998.15).append(data['Cwz pond']))
data['water io'] = data['Cwz inflow'] - data['water used']
data['vol per ft'] = data['water io'] / data['elevation change']

data = data[data['vol per ft'] > 400]
data = data[data['vol per ft'] <600]

plt.plot(data['Cwz Sw1 head'], data['vol per ft'],'o',color='g')
plt.xlabel('Cwz pond')
plt.ylabel('vol per ft')
slope_vol, intercept_vol, r_value, p_value, std_err = stats.linregress(data['Cwz Sw1 head'],data['vol per ft'])
head = data['Cwz Sw1 head'].tolist()
plt.plot(head, [slope_vol * h + intercept_vol for h in head], '+', color='r')
plt.show()

plt.plot(data[xlabel], data[ylabel],'o',color='b')
plt.xlabel(xlabel)
plt.ylabel(ylabel)
slope_hk, intercept_hk, r_value, p_value, std_err = stats.linregress(data['Cwz Sw1 head'],data['h/k'])
plt.plot(head, [slope_hk * h + intercept_hk for h in head], '+', color='r')
plt.show()
data.to_csv(output_path)
