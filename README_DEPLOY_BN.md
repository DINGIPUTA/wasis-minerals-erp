# ওয়াসিস মিনারেল এন্ড মেটালাস লিমিটেড — Mobile ERP

এটি মোবাইল-ফ্রেন্ডলি Flask ERP-এর server-ready package।

## গুরুত্বপূর্ণ
এটি ZIP ফাইল সরাসরি ফোনে খুলে চালানোর সফটওয়্যার নয়। Hosting/server-এ deploy করলে একটি web link পাওয়া যাবে, সেই link Chrome-এ খুলে মোবাইল থেকে ব্যবহার করা যাবে।

## Login
Username: admin
Password: admin123

প্রথম Login-এর পর password পরিবর্তন করার ব্যবস্থা/নিরাপত্তা যোগ করা উচিত।

## Hosting
Flask/Gunicorn চালাতে পারে এমন hosting ব্যবহার করুন। SQLite ব্যবহার করা হয়েছে; production-এ persistent disk/backup নিশ্চিত করতে হবে। ১০–১৫ জন একসাথে ব্যবহার করলে PostgreSQL-এ নেওয়া আরও ভালো।

## PWA
static/manifest.json এবং static/sw.js রাখা হয়েছে, তাই HTTPS-এ deploy করার পর Chrome-এর Add to Home Screen ব্যবহার করা যাবে।
