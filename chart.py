#!/usr/bin/env python3
import datetime
from dateutil.parser import parse
import yaml
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

with open('themes.yaml') as f:
    ts = yaml.load(f)

days = [(parse(day) - datetime.datetime(2014, 4, 19)).days for day in sorted(ts) if day != '0-misc']
nums = [ts[day]['num'] for day in sorted(ts) if day != '0-misc']
user_nums = [ts[day]['user_num'] for day in sorted(ts) if day != '0-misc']

ax1 = plt.axes()
ax2 = ax1.twinx()

ax1.plot(days, user_nums, '.-', color='lightsteelblue', linewidth=2)
ax2.plot(days, nums, '.-', color='palevioletred', linewidth=2)

ax1.set_ylim(0, max(user_nums) + 15)
ax1.xaxis.set_major_locator(plt.MultipleLocator(5))
ax1.yaxis.set_major_locator(plt.MultipleLocator(50))
ax2.set_ylim(0, max(nums) + 15)
ax2.xaxis.set_major_locator(plt.MultipleLocator(5))
ax2.yaxis.set_major_locator(plt.MultipleLocator(25))
ax2.grid(True)

fp = FontProperties(fname='/Library/fonts/Hiragino Sans GB W3.otf')
ax1.set_xlabel('回数', fontproperties=fp)
ax1.set_ylabel('累計参加者数', fontproperties=fp)
ax2.set_ylabel('作品数', fontproperties=fp)

p1 = plt.Rectangle((0, 0), 1, 1, fc="lightsteelblue")
p2 = plt.Rectangle((0, 0), 1, 1, fc="palevioletred")
ax1.legend([p1, p2], ['累計参加者数', '作品数'], loc='upper left', prop=fp)

#ax1.legend()

#plt.title('作品数の変化', fontproperties=fp)
plt.savefig('html/chart.svg')
