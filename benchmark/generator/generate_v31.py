#!/usr/bin/env python3
"""Blind-test generator v3.1 (recalibrated registration rates, bursty as knob): calibrated to public official aggregates, 24 feeds, households.
PRIVATE. Truth only in truth/. Usage: generate_v3.py --n N --seed S --offset O --out DIR [--months 3]
"""
import csv, json, random, os, argparse
from datetime import date, timedelta

FIRST_M = ["Ramesh","Suresh","Mahesh","Dinesh","Rajesh","Ganesh","Harish","Naresh","Anil","Sunil","Vinod","Ashok","Vijay","Ajay","Sanjay","Manoj","Prakash","Ravi","Arun","Kiran","Mohan","Shankar","Krishna","Venkat","Satish","Rakesh","Deepak","Anand","Gopal","Madhav","Baban","Tukaram","Eknath","Pandurang","Mohammed","Abdul","Imran","Salim","Iqbal","Rafiq","Joseph","Thomas","George","Sunny","Harpreet","Gurmeet","Baldev","Manpreet","Irfan","Farhan"]
FIRST_F = ["Sunita","Anita","Kavita","Savita","Geeta","Seeta","Meena","Rekha","Lata","Usha","Asha","Pushpa","Kamla","Shanta","Radha","Sarita","Mangala","Shobha","Vandana","Pratibha","Fatima","Ayesha","Zainab","Maryam","Rukhsana","Mary","Alice","Grace","Sukhwinder","Manjit","Amarjit","Parveen","Shabana","Nasreen","Anjali","Pooja","Sneha","Vijaya","Lakshmi","Saraswati"]
SUR = ["Patil","Desai","Kulkarni","Joshi","Deshpande","Sharma","Verma","Gupta","Agarwal","Singh","Chauhan","Rathod","Yadav","Chavan","More","Jadhav","Shinde","Pawar","Kadam","Bhosale","Khan","Shaikh","Ansari","Qureshi","Fernandes","D'Souza","Pereira","Nair","Menon","Iyer","Reddy","Naidu","Das","Mukherjee","Banerjee","Chatterjee","Dutta","Thakur","Mehta","Shah"]
VARIANTS = {"Kulkarni":["Kulkarni","Kulakarni","Kulkrni","Kulkarnee"],"Mohammed":["Mohammed","Mohammad","Muhammed","Md."],"Sharma":["Sharma","Sarma","Sharam"],"Singh":["Singh","Sinha","Sinh"],"Shaikh":["Shaikh","Sheikh","Shaihk"],"Pawar":["Pawar","Powar","Paawar"],"Joshi":["Joshi","Josy","Jhoshee"],"Patil":["Patil","Patel","Paatil"],"Suresh":["Suresh","Surehs","Sursesh"],"Ramesh":["Ramesh","Ramaesh","Rames"],"Geeta":["Geeta","Gita","Geetha"],"Sunita":["Sunita","Suneeta","Sunitaa"]}
# district: (name, state, registration_rate, rural_share)
DISTRICTS = [("Pune","Maharashtra",0.95,0.35,None),("Satara","Maharashtra",0.93,0.65,None),("Nashik","Maharashtra",0.94,0.55,None),
             ("Belagavi","Karnataka",0.93,0.6,None),("Patna","Bihar",0.60,0.55,None),("Gaya","Bihar",0.55,0.75,None),
             ("Lucknow","UttarPradesh",0.78,0.6,None),("Kochi","Kerala",0.97,0.4,None),
             ("Darbhanga","Bihar",0.52,0.8,60),("Azamgarh","UttarPradesh",0.75,0.75,60)]
SCHEMES = [("OPS",8200),("IGNOAPS",1000),("StateWidow",1500),("EPS95",2350)]
HOSPITALS = ["District Civil Hospital","Sub-District Hospital Ghodegaon","City General Hospital","PHC Wagholi","Rural Hospital Shirur","Private Multispecialty Hospital"]
TOLLS = ["Khed-Shivapur","Anewadi","Khandala","Shirwal","Khalapur"]
BANKS = ["SBIN00DEMO1","PUNB0DEMO02","BKID0DEMO03","MAHB0DEMO04"]
SNAP = date(2026, 11, 3)

def months_back(n):
    d = SNAP.replace(day=1); out = []
    for _ in range(n):
        out.append(d); d = (d - timedelta(days=1)).replace(day=1)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", required=True)
    ap.add_argument("--months", type=int, default=3)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dead-frac", type=float, default=0.042)
    ap.add_argument("--fraud-frac", type=float, default=0.38)
    ap.add_argument("--misscert-frac", type=float, default=0.05)
    ap.add_argument("--recent-frac", type=float, default=0.12)
    ap.add_argument("--lowreg-boost", type=float, default=1.0)
    ap.add_argument("--lowvol-frac", type=float, default=0.0)
    ap.add_argument("--rural-lag-mean", type=float, default=20.0)
    ap.add_argument("--decoy-frac", type=float, default=0.0)
    ap.add_argument("--masked-frac", type=float, default=0.0)
    ap.add_argument("--irreg-frac", type=float, default=0.0)
    ap.add_argument("--famutil-frac", type=float, default=0.55)
    ap.add_argument("--bursty-frac", type=float, default=0.30)
    a = ap.parse_args()
    random.seed(a.seed)
    F = os.path.join(a.out, "feeds"); T = os.path.join(a.out, "truth")
    os.makedirs(F, exist_ok=True); os.makedirs(T, exist_ok=True)
    fa = lambda i: "9999%08d" % (10000000 + i)
    fp = lambda i: "FAKE%s%04d%s" % (chr(65+i%26), i%10000, chr(65+(i*7)%26))
    fph = lambda i: "10000%05d" % (10000 + i)
    fac = lambda i: "9%010d" % (7000000000 + i)
    def variant(name):
        v = VARIANTS.get(name)
        if v and random.random() < 0.45: return random.choice(v)
        if random.random() < 0.03:
            p = random.randrange(len(name)); return name[:p] + name[p+1:]
        return name
    def dob_noise(d):
        r = random.random()
        if r < 0.05 and d.day <= 12: return d.replace(month=d.day, day=d.month)
        if r < 0.09:
            try: return d.replace(year=d.year + random.choice([1,-1,2]))
            except ValueError: return d
        return d

    # ---------- persons + households ----------
    persons = []
    N = a.n
    for k in range(N):
        i = a.offset + k
        g = "M" if random.random() < 0.58 else "F"
        fn = random.choice(FIRST_M if g=="M" else FIRST_F); sn = random.choice(SUR)
        age = int(random.triangular(60, 95, 72))
        dob = date(SNAP.year-age, random.randint(1,12), random.randint(1,28))
        _wts = [(1.0 + (a.lowreg_boost-1.0)*(1.0-d[2])) for d in DISTRICTS]
        dist, state, reg_rate, rural_share, lag_mean = random.choices(DISTRICTS, weights=_wts)[0]
        rural = random.random() < rural_share
        wealth = min(5, max(1, int(random.gauss(2.6 if rural else 3.4, 1.1)) + (0 if rural else 0)))
        scheme, base = SCHEMES[0] if random.random() < 0.30 else (SCHEMES[1] if random.random() < 0.45 else random.choice(SCHEMES[2:]))
        persons.append(dict(pid="P%08d"%(i+1), fn=fn, sn=sn, gender=g, dob=dob, age=age,
            aadhaar=fa(i), pan=fp(i), phone=fph(i), acct=fac(i), ifsc=random.choice(BANKS),
            district=dist, state=state, reg_rate=reg_rate, rural=rural, wealth=wealth, lag_mean=lag_mean,
            scheme=scheme, amount=base+random.randint(0,800),
            tag="TG%08d"%(90000000+i), plate="MH%02dXX%04d"%(random.randint(10,14), 1000+i%9000),
            consumer="U%09d"%(300000000+i), epic="EPIC%07d"%(4000000+i%999999),
            uan="UAN%09d"%(100000000+i), nps="NPS%08d"%(50000000+i), lic="LIC%09d"%(200000000+i),
            ration="RC%10d"%(1000000000+i), lpg="LPG%09d"%(700000000+i),
            prop="PROP%08d"%(80000000+i), pmjay="PMJAY%08d"%(60000000+i), mgn="MGN%09d"%(300000000+i),
            dl="DL%09d"%(400000000+i), pp="P%08d"%(90000000+i),
            hh=None, addr=None))
    # households: pair 40% into 2-pensioner households sharing surname+utilities
    idxs = list(range(N)); random.shuffle(idxs)
    hh_id = 0
    taken = set()
    for a_i in idxs[:int(N*0.4)]:
        if a_i in taken: continue
        b_i = random.choice(idxs)
        if b_i == a_i or b_i in taken: continue
        hh_id += 1
        sn = persons[a_i]["sn"]
        for j in (a_i, b_i):
            persons[j]["hh"] = hh_id; persons[j]["sn"] = sn
        addr = "%d, %s Nagar, %s %s" % (random.randint(1,400), random.choice(["Shivaji","Gandhi","Nehru","Ambedkar","Tilak"]), persons[a_i]["district"], "4%05d" % random.randint(1,99999))
        for j in (a_i, b_i): persons[j]["addr"] = addr
        for k2, pref in (("consumer","U"),("lpg","LPG"),("ration","RC"),("prop","PROP")):
            persons[b_i][k2] = persons[a_i][k2]
        taken.add(a_i); taken.add(b_i)
    for p in persons:
        if p["addr"] is None:
            p["addr"] = "%d, %s Nagar, %s 4%05d" % (random.randint(1,400), random.choice(["Shivaji","Gandhi","Nehru","Ambedkar","Tilak"]), p["district"], random.randint(1,99999))

    # ---------- hidden truth ----------
    truth = {}
    for p in persons:
        t = dict(pid=p["pid"], alive=True, death_date=None, registered=False, in_registry=False,
                 hospital_death=False, in_hospital_feed=False, family_keeps_sim=False,
                 family_keeps_tag=False, family_withdraws=False, family_pays_utility=False,
                 electoral_deleted=False, offline_but_alive=False, alive_bank_quiet=False,
                 dormant=False, missed_life_cert=False, pension_still_paid=True, low_volume_living=False, single_feed_quiet="", fully_masked=False, irregular_baseline=False, bursty_dead=False)
        truth[p["pid"]] = t
    n_dead = int(N * a.dead_frac)
    for i in random.sample(range(N), n_dead):
        p = persons[i]; t = truth[p["pid"]]
        t["alive"] = False
        dd = SNAP - timedelta(days=random.randint(2,30) if random.random()<a.recent_frac else random.randint(15,360))
        t["death_date"] = dd.isoformat()
        t["registered"] = random.random() < p["reg_rate"]
        if t["registered"]:
            lm = p.get("lag_mean")
            lag = random.randint(3,45) if not p["rural"] else min(120, int(random.expovariate(1.0/a.rural_lag_mean))+3)
            if lm: lag = min(180, int(random.expovariate(1.0/lm))+5)
            t["in_registry"] = (dd + timedelta(days=lag)) <= SNAP
        t["hospital_death"] = random.random() < (0.5 if p["age"] >= 70 else 0.4)
        t["in_hospital_feed"] = t["hospital_death"] and random.random() < (0.75 if p["age"] >= 70 else 0.55)
        t["family_keeps_sim"] = random.random() < 0.28
        t["family_keeps_tag"] = random.random() < 0.20
        t["family_withdraws"] = random.random() < a.fraud_frac
        t["family_pays_utility"] = random.random() < a.famutil_frac
        if random.random() < a.masked_frac:
            t["fully_masked"] = True
            t["registered"] = False; t["in_registry"] = False
            t["family_keeps_sim"] = True; t["family_withdraws"] = True
            t["family_pays_utility"] = True; t["electoral_deleted"] = False
        t["electoral_deleted"] = (dd + timedelta(days=random.randint(60,180))) <= SNAP and random.random() < 0.5
        t["pension_still_paid"] = random.random() > 0.10
        t["bursty_dead"] = random.random() < a.bursty_frac
    for p in persons:
        t = truth[p["pid"]]
        if not t["alive"]: continue
        off_rate = 0.12 if p["age"] >= 80 else (0.08 if p["age"] >= 70 else 0.05)
        r = random.random()
        if r < off_rate: t["offline_but_alive"] = True
        elif r < off_rate + 0.06: t["alive_bank_quiet"] = True
        if t["alive_bank_quiet"] and random.random() < 0.4: t["dormant"] = True
        if not (t["offline_but_alive"] or t["alive_bank_quiet"]) and random.random() < a.lowvol_frac: t["low_volume_living"] = True
        if not (t["offline_but_alive"] or t["alive_bank_quiet"] or t["low_volume_living"]) and random.random() < a.irreg_frac: t["irregular_baseline"] = True
        if not (t["offline_but_alive"] or t["alive_bank_quiet"] or t["low_volume_living"] or t["irregular_baseline"]) and random.random() < a.decoy_frac:
            t["single_feed_quiet"] = random.choice(["telecom","bank","utility"])
            t["decoy_quiet_from"] = (SNAP - timedelta(days=random.randint(60,150))).isoformat()
        if random.random() < a.misscert_frac: t["missed_life_cert"] = True

    json.dump(dict(meta=dict(n=N, seed=a.seed, offset=a.offset, months=a.months, dead_frac=a.dead_frac)), open(os.path.join(T, "meta.json"), "w"))
    with open(os.path.join(T, "truth.json"), "w") as f:
        json.dump(truth, f)
    globals().update(persons=persons, truth=truth, F=F, a=a, variant=variant, dob_noise=dob_noise)
    emit_feeds()

def emit_feeds():
    persons = globals()["persons"]; truth = globals()["truth"]; F = globals()["F"]; a = globals()["a"]
    variant = globals()["variant"]; dob_noise = globals()["dob_noise"]
    w = {}
    def wr(name, hdr):
        f = open(os.path.join(F, name), "w", newline=""); c = csv.writer(f); c.writerow(hdr); w[name] = f; return c
    pm = wr("pension_master.csv", ["pensioner_id","full_name","dob","gender","aadhaar_number","pan","bank_account","ifsc","mobile","address","district","state","scheme_code","monthly_amount","pension_start_date","pension_status"])
    pd_ = wr("pension_disbursements.csv", ["pensioner_id","month","amount","credit_date","bank_account"])
    aad = wr("aadhaar_registry.csv", ["aadhaar_number","name","dob","gender","address","mobile","enrolment_date","last_update_date"])
    dr = wr("death_registry.csv", ["registration_no","deceased_name","dob","gender","date_of_death","registration_date","place_of_death","district","aadhaar_number"])
    br = wr("birth_register.csv", ["registration_no","child_name","dob","gender","father_name","mother_name","district","registration_date"])
    mr = wr("marriage_register.csv", ["registration_no","spouse1_name","spouse2_name","marriage_date","registration_date","district"])
    vc = wr("vaccination_records.csv", ["aadhaar_number","name","dob","vaccine","dose_no","vaccination_date","centre","district"])
    ed = wr("education_records.csv", ["person_name","dob","qualification","institution","year_of_passing","district"])
    gst = wr("gst_registrations.csv", ["gstin","legal_name","pan","registration_date","status","district"])
    er = wr("electoral_roll.csv", ["epic_number","name","dob","gender","address","district","status","deletion_date"])
    pp = wr("passport_registry.csv", ["passport_no","name","dob","issue_date","expiry_date","district"])
    dl = wr("driving_licence.csv", ["dl_number","name","dob","issue_date","valid_upto","vehicle_class","district"])
    rc = wr("vehicle_rc.csv", ["registration_no","owner_name","owner_aadhaar","vehicle_class","registration_date","fitness_upto","district"])
    tf = wr("toll_fastag.csv", ["tag_id","vehicle_plate","txn_timestamp","toll_plaza","amount"])
    bk = wr("bank_kyc.csv", ["account_number","name","dob","account_opened","last_kyc_refresh","nominee_registered","account_status"])
    bt = wr("bank_transactions.csv", ["account_number","txn_date","txn_type","amount","channel","narration"])
    tx = wr("tax_pan_activity.csv", ["pan","financial_year","itr_filed","filing_date"])
    ep = wr("epfo_uan.csv", ["uan","name","dob","aadhaar_number","status","last_contribution_month","pension_scheme_linked"])
    nps = wr("nps_accounts.csv", ["pran","name","dob","status","last_contribution_month","tier"])
    lic = wr("lic_insurance.csv", ["policy_no","name","dob","premium_amount","premium_frequency","last_premium_date","status"])
    rat = wr("ration_pds.csv", ["ration_card_no","member_name","member_aadhaar","relationship","month","offtake_kg","district"])
    lpg = wr("lpg_refills.csv", ["consumer_id","consumer_name","address","booking_date","delivery_date","subsidy_amount"])
    pj = wr("pmjay_claims.csv", ["pmjay_id","patient_name","dob","gender","hospital_name","admission_date","discharge_date","outcome","claim_amount","district"])
    hr = wr("hospital_records.csv", ["patient_name","dob","gender","admit_date","discharge_date","outcome","hospital_name","district"])
    mg = wr("mgnrega_work.csv", ["job_card_no","name","district","month","workdays","wages_paid","payment_date"])
    mp = wr("municipal_property.csv", ["property_id","owner_name","address","district","annual_tax","last_paid_date","mutation_date"])
    ta = wr("telecom_activity.csv", ["mobile","month","calls_made","sms_sent","data_mb","last_activity_date"])
    ub = wr("utility_bills.csv", ["consumer_id","consumer_name","service_address","month","units_kwh","bill_paid_date"])
    lc = wr("life_certificates.csv", ["pensioner_id","certificate_id","submission_date","channel","status"])

    hh_map = {}
    for _p in persons:
        if _p["hh"]: hh_map.setdefault(_p["hh"], []).append(_p["pid"])
    ms = months_back(a.months)
    regno = 100000
    for p in persons:
        t = truth[p["pid"]]
        dead = not t["alive"]
        dd = date.fromisoformat(t["death_date"]) if dead else None
        nm = variant(p["fn"]) + " " + variant(p["sn"])
        dob_s = dob_noise(p["dob"]).isoformat() if random.random() < 0.09 else p["dob"].isoformat()
        # household-level: if sharing household with an ALIVE spouse, household feeds continue regardless
        spouse_alive = False
        if p["hh"]:
            for qpid in hh_map[p["hh"]]:
                if qpid != p["pid"]:
                    spouse_alive = truth[qpid]["alive"]; break
        # 1-2 pension master + disbursements
        status = "ACTIVE" if (not dead or t["pension_still_paid"]) else "STOPPED"
        pm.writerow([p["pid"], nm, dob_s, p["gender"], p["aadhaar"], p["pan"], p["acct"], p["ifsc"], p["phone"], p["addr"], p["district"], p["state"], p["scheme"], p["amount"], (p["dob"].replace(year=p["dob"].year+60)).isoformat(), status])
        for m in ms:
            credit = m.replace(day=min(28, random.randint(5,12)))
            if credit > SNAP: continue
            if dead and credit > dd and not t["pension_still_paid"]: continue
            pd_.writerow([p["pid"], m.strftime("%Y-%m"), p["amount"], credit.isoformat(), p["acct"]])
        # 3 aadhaar (enrol 2011-2016; ~15% stale address: keep an old address variant)
        enrol = date(random.randint(2011,2016), random.randint(1,12), random.randint(1,28))
        upd = enrol if random.random() < 0.7 else date(random.randint(2017,2024), random.randint(1,12), random.randint(1,28))
        addr_a = p["addr"] if random.random() < 0.85 else "%d, %s Colony, %s 4%05d" % (random.randint(1,400), random.choice(["Nehru","Patel","Bose"]), p["district"], random.randint(1,99999))
        aad.writerow([p["aadhaar"], nm, dob_s, p["gender"], addr_a, p["phone"], enrol.isoformat(), upd.isoformat()])
        # 4 death registry
        if dead and t["in_registry"]:
            regno += 1
            lm = p.get("lag_mean")
            lag = random.randint(3,45) if not p["rural"] else min(120, int(random.expovariate(1.0/a.rural_lag_mean))+3)
            if lm: lag = min(180, int(random.expovariate(1.0/lm))+5)
            dr.writerow(["DR%08d"%regno, variant(p["fn"])+" "+variant(p["sn"]), dob_noise(p["dob"]).isoformat() if random.random()<0.10 else p["dob"].isoformat(), p["gender"], dd.isoformat(), min(dd+timedelta(days=lag), SNAP).isoformat(), random.choice(["Residence","Hospital","Other"]), p["district"], p["aadhaar"] if random.random()<0.70 else ""])
        # 5 birth register (8%, urban-skewed)
        if random.random() < (0.14 if not p["rural"] else 0.03):
            regno += 1
            br.writerow(["BR%08d"%regno, nm, p["dob"].isoformat(), p["gender"], variant(random.choice(FIRST_M))+" "+p["sn"], variant(random.choice(FIRST_F))+" "+p["sn"], p["district"], (p["dob"]+timedelta(days=random.randint(10,400))).isoformat()])
        # 6 marriage register (12%)
        if random.random() < 0.12:
            regno += 1
            md = date(p["dob"].year+random.randint(20,30), random.randint(1,12), random.randint(1,28))
            sp = (variant(random.choice(FIRST_F)) if p["gender"]=="M" else variant(random.choice(FIRST_M)))+" "+variant(p["sn"])
            mr.writerow(["MR%08d"%regno, nm if p["gender"]=="M" else sp, sp if p["gender"]=="M" else nm, md.isoformat(), (md+timedelta(days=random.randint(0,120))).isoformat(), p["district"]])
        # 7 vaccination (85%, 2021-2023, 2-3 doses)
        if random.random() < 0.85:
            for dose in range(1, random.choice([3,3,4])):
                vd = date(random.randint(2021,2022), random.randint(1,12), random.randint(1,28)) if dose<3 else date(random.randint(2022,2023), random.randint(1,12), random.randint(1,28))
                vc.writerow([p["aadhaar"], nm, p["dob"].isoformat(), random.choice(["Covishield","Covaxin"]), dose, vd.isoformat(), random.choice(["PHC Wagholi","District Hospital","Urban Health Centre"]), p["district"]])
        # 8 education (10%)
        if random.random() < 0.10:
            ed.writerow([nm, p["dob"].isoformat(), random.choice(["BA","BSc","BCom","MA","ITI","BEd"]), random.choice(["Government College","State University","District College"]), p["dob"].year+random.randint(20,25), p["district"]])
        # 9 GST (1%)
        if random.random() < 0.01:
            gst.writerow(["27FAKE%05dZ%d"%(random.randint(1,99999), random.randint(1,9)), nm, p["pan"], date(random.randint(2017,2024), random.randint(1,12), random.randint(1,28)).isoformat(), "ACTIVE", p["district"]])
        # 10 electoral
        if dead and t["electoral_deleted"]:
            er.writerow([p["epic"], nm, p["dob"].isoformat(), p["gender"], p["addr"], p["district"], "DELETED", min(dd+timedelta(days=random.randint(60,180)), SNAP).isoformat()])
        elif random.random() < 0.96:
            er.writerow([p["epic"], nm, dob_noise(p["dob"]).isoformat() if random.random()<0.06 else p["dob"].isoformat(), p["gender"], p["addr"], p["district"], "ACTIVE", ""])
        # 11 passport (6%, wealth-skewed)
        if random.random() < 0.02*p["wealth"]:
            iss = date(random.randint(2005,2022), random.randint(1,12), random.randint(1,28))
            pp.writerow([p["pp"], nm, p["dob"].isoformat(), iss.isoformat(), iss.replace(year=iss.year+10).isoformat(), p["district"]])
        # 12 driving licence (men 25%, women 6%, age-decay)
        dl_p = (0.25 if p["gender"]=="M" else 0.06) * max(0.3, 1-(p["age"]-60)/40)
        if random.random() < dl_p:
            iss = date(random.randint(1995,2022), random.randint(1,12), random.randint(1,28))
            dl.writerow([p["dl"], nm, dob_noise(p["dob"]).isoformat() if random.random()<0.08 else p["dob"].isoformat(), iss.isoformat(), iss.replace(year=iss.year+random.choice([5,20])).isoformat(), random.choice(["MCWG","LMV","LMV-TR"]), p["district"]])
        # 13 vehicle RC + 14 FASTag
        owns_vehicle = random.random() < 0.05*p["wealth"]
        if owns_vehicle:
            regd = date(random.randint(2008,2024), random.randint(1,12), random.randint(1,28))
            rc.writerow([p["plate"], nm, p["aadhaar"], random.choice(["2W","4W"]), regd.isoformat(), regd.replace(year=regd.year+15).isoformat(), p["district"]])
            for m in ms:
                if dead and not t["family_keeps_tag"] and m > dd.replace(day=1): continue
                for _ in range(random.randint(0,5)):
                    d = m.replace(day=random.randint(1,28))
                    if dead and not t["family_keeps_tag"] and d > dd: continue
                    if d > SNAP: continue
                    tf.writerow([p["tag"], p["plate"], d.isoformat()+"T%02d:%02d:00"%(random.randint(5,22), random.randint(0,59)), random.choice(TOLLS), random.choice([45,65,90,120])])
        # 15 bank KYC (dormancy trap) + 16 transactions
        opened = date(random.randint(2005,2020), random.randint(1,12), random.randint(1,28))
        bk.writerow([p["acct"], nm, dob_s, opened.isoformat(), (opened.replace(year=min(opened.year+random.randint(2,8), 2025)) if random.random()<0.6 else opened).isoformat(), random.choice(["YES","NO","YES"]), "DORMANT" if t["dormant"] else "ACTIVE"])
        quiet_from = None
        if t["offline_but_alive"] or t["alive_bank_quiet"]:
            quiet_from = SNAP - timedelta(days=random.randint(200,720) if t["dormant"] else random.randint(120,360))
        for m in ms:
            if dead:
                n_tx = random.choice([0,0,1,3,7,12]) if t.get("bursty_dead") and m <= dd.replace(day=1) else 0
            else:
                n_tx = random.randint(1,5)
            if t.get("irregular_baseline"): n_tx = random.choice([0,0,1,3,7,12])
            if t.get("low_volume_living"): n_tx = 1 if random.random() < 0.45 else 0
            if t.get("single_feed_quiet")=="bank" and m >= date.fromisoformat(t["decoy_quiet_from"]).replace(day=1): n_tx = 0
            if (t["offline_but_alive"] or t["alive_bank_quiet"]) and quiet_from and m >= quiet_from.replace(day=1): n_tx = 0
            for _ in range(n_tx):
                d = m.replace(day=random.randint(1,28))
                if d > SNAP: continue
                bt.writerow([p["acct"], d.isoformat(), "DR", random.randint(100,9000), random.choice(["UPI","ATM","NEFT","IMPS","CASH"]), random.choice(["POS PURCHASE","ATM WDL","UPI PAYMENT","TRANSFER"])])
            if dead and t["family_withdraws"] and m > dd.replace(day=1):
                d = m.replace(day=min(28, random.randint(6,13)))
                if d <= SNAP: bt.writerow([p["acct"], d.isoformat(), "DR", p["amount"], "ATM", "ATM WDL"])
        # 17 tax
        if random.random() < 0.05*p["wealth"]:
            for fy, end in (("2024-25", date(2025,7,31)), ("2025-26", date(2026,7,31))):
                if dead and end > dd: continue
                tx.writerow([p["pan"], fy, "YES", (end-timedelta(days=random.randint(0,120))).isoformat()])
        # 18 EPFO (30% history; 5% still contributing until death)
        if random.random() < 0.30:
            working = random.random() < 0.05
            last = (min(dd.replace(day=1) if dead else SNAP, SNAP)) if working else date(p["dob"].year+random.randint(58,60), random.randint(1,12), 1)
            ep.writerow([p["uan"], nm, p["dob"].isoformat(), p["aadhaar"], "ACTIVE" if working and not dead else "INACTIVE", last.strftime("%Y-%m"), "YES" if p["scheme"]=="EPS95" else "NO"])
        # 19 NPS (5%)
        if random.random() < 0.05:
            nps.writerow([p["nps"], nm, p["dob"].isoformat(), "ACTIVE" if not dead else "FROZEN", (min(dd, SNAP) if dead else SNAP).strftime("%Y-%m"), "I"])
        # 20 LIC (25%, wealth-skewed)
        if random.random() < 0.06*p["wealth"]:
            last_prem = SNAP - timedelta(days=random.randint(10,300))
            lapse = dead and not (t["family_withdraws"] and random.random()<0.5)
            if lapse and dd < last_prem: last_prem = dd - timedelta(days=random.randint(0,60))
            lic.writerow([p["lic"], nm, p["dob"].isoformat(), random.randint(2000,30000), random.choice(["Monthly","Quarterly","Yearly"]), last_prem.isoformat(), "LAPSED" if lapse and (SNAP-last_prem).days>180 else "ACTIVE"])
        # 21 ration (92%, household; offtake continues while any member alive)
        if random.random() < 0.92:
            rel = "Self"
            for m in ms:
                if dead and not (t["family_pays_utility"] or spouse_alive) and m > dd.replace(day=1): continue
                rat.writerow([p["ration"], nm, p["aadhaar"], rel, m.strftime("%Y-%m"), random.randint(5,25), p["district"]])
        # 22 LPG (90% household, ~2 refills/quarter)
        if random.random() < 0.90:
            for m in ms:
                if random.random() < 0.67:
                    if dead and not (t["family_pays_utility"] or spouse_alive) and m > dd.replace(day=1): continue
                    bd = m.replace(day=random.randint(1,28))
                    if bd > SNAP: continue
                    lpg.writerow([p["lpg"], nm, p["addr"], bd.isoformat(), (bd+timedelta(days=random.randint(1,6))).isoformat(), random.randint(0,600)])
        # 23 PM-JAY claims + 24 hospital
        if dead and t["in_hospital_feed"]:
            admit = dd - timedelta(days=random.randint(0,6))
            hr.writerow([variant(p["fn"])+" "+variant(p["sn"]), dob_noise(p["dob"]).isoformat() if random.random()<0.12 else p["dob"].isoformat(), p["gender"], admit.isoformat(), dd.isoformat(), "DIED", random.choice(HOSPITALS), p["district"]])
            if p["age"] >= 70 and random.random() < 0.7:
                pj.writerow([p["pmjay"], variant(p["fn"])+" "+variant(p["sn"]), dob_noise(p["dob"]).isoformat() if random.random()<0.12 else p["dob"].isoformat(), p["gender"], random.choice(HOSPITALS[:5]), admit.isoformat(), dd.isoformat(), "DIED", random.randint(15000,400000), p["district"]])
        elif not dead and random.random() < 0.18:
            d = SNAP - timedelta(days=random.randint(5,300))
            hr.writerow([variant(p["fn"])+" "+variant(p["sn"]), dob_noise(p["dob"]).isoformat() if random.random()<0.12 else p["dob"].isoformat(), p["gender"], d.isoformat(), (d+timedelta(days=random.randint(1,7))).isoformat(), "DISCHARGED", random.choice(HOSPITALS), p["district"]])
        # 25 MGNREGA (rural ~22% work, stops at death)
        if p["rural"] and random.random() < (0.22 if p["age"]<75 else 0.08):
            for m in ms:
                if dead and m >= dd.replace(day=1): continue
                wd = random.randint(0,12)
                if wd == 0: continue
                mg.writerow([p["mgn"], nm, p["district"], m.strftime("%Y-%m"), wd, wd*random.randint(200,300), m.replace(day=min(28, random.randint(15,28))).isoformat()])
        # 26 municipal property (65% own; mutation lag years)
        if random.random() < 0.65:
            mutated = dead and random.random() < 0.3 and (dd+timedelta(days=random.randint(90,400))) <= SNAP
            mp.writerow([p["prop"], nm, p["addr"], p["district"], random.randint(800,12000), (SNAP-timedelta(days=random.randint(30,400))).isoformat() if (not dead or t["family_pays_utility"] or spouse_alive or random.random()<0.5) else (dd-timedelta(days=random.randint(0,200))).isoformat(), min(dd+timedelta(days=random.randint(90,400)), SNAP).isoformat() if mutated else ""])
        # 27 telecom
        for m in ms:
            active = True; calls = random.randint(10,120); data = random.randint(50,4000)
            if t.get("irregular_baseline"):
                if random.random() < 0.3: active = False
                calls = random.choice([0,5,40,150]); data = random.choice([0,100,2000])
            if t.get("low_volume_living"): calls = random.randint(2,15); data = random.randint(5,300)
            if t.get("single_feed_quiet")=="telecom" and m >= date.fromisoformat(t["decoy_quiet_from"]).replace(day=1): active = False
            if dead:
                if t["family_keeps_sim"] and m > dd.replace(day=1): calls = random.randint(3,40); data = random.randint(10,800)
                elif m > dd.replace(day=1): active = False
            if t["offline_but_alive"] and quiet_from and m >= quiet_from.replace(day=1): active = False
            if dead and t.get("bursty_dead") and m <= dd.replace(day=1) and random.random() < 0.35: active = False
            if dead and t.get("bursty_dead") and active: calls = random.choice([0,5,40,150]); data = random.choice([0,100,2000])
            if not active: continue
            last = m.replace(day=random.randint(1,28))
            if dead and not t["family_keeps_sim"]: last = min(last, dd)
            if last > SNAP: last = SNAP
            ta.writerow([p["phone"], m.strftime("%Y-%m"), calls, random.randint(0,30), data, last.isoformat()])
        # 28 electricity (household)
        lapse_from = None
        if dead and not (t["family_pays_utility"] or spouse_alive):
            lapse_from = (dd+timedelta(days=random.randint(30,90))).replace(day=1)
        for m in ms:
            if lapse_from and m >= lapse_from: continue
            if t["offline_but_alive"] and random.random()<0.3: continue
            if t.get("single_feed_quiet")=="utility" and m >= date.fromisoformat(t["decoy_quiet_from"]).replace(day=1): continue
            ub.writerow([p["consumer"], nm, p["addr"], m.strftime("%Y-%m"), random.randint(30,400), m.replace(day=min(28, random.randint(8,20))).isoformat()])
        # 29 life certificates
        alive_nov25 = (not dead) or dd > date(2025,11,30)
        if alive_nov25 and not t["missed_life_cert"]:
            lc.writerow([p["pid"], "LC%09d"%(500000000+hash(p["pid"])%99999999), date(2025,11,random.randint(1,28)).isoformat(), random.choice(["JeevanPramaan-Face","JeevanPramaan-Fingerprint","Physical","BankBranch"]), "VERIFIED"])
    for f in w.values(): f.close()
    # person map (private)
    T = os.path.join(os.path.dirname(F), "truth")
    with open(os.path.join(T, "person_map.csv"), "w", newline="") as f:
        c = csv.writer(f); c.writerow(["pid","name","dob","aadhaar","pan","phone","acct","tag","consumer","epic","uan","ration","lpg","prop","hh"])
        for p in persons:
            c.writerow([p["pid"], p["fn"]+" "+p["sn"], p["dob"], p["aadhaar"], p["pan"], p["phone"], p["acct"], p["tag"], p["consumer"], p["epic"], p["uan"], p["ration"], p["lpg"], p["prop"], p["hh"] or ""])

if __name__ == "__main__":
    main()
    persons = globals()["persons"]; truth = globals()["truth"]; a = globals()["a"]
    alive = sum(1 for t in truth.values() if t["alive"])
    print(json.dumps(dict(n=a.n, alive=alive, dead=a.n-alive,
        dead_in_registry=sum(1 for t in truth.values() if t["in_registry"]),
        dead_still_paid=sum(1 for t in truth.values() if not t["alive"] and t["pension_still_paid"]),
        households=len(set(p["hh"] for p in persons if p["hh"])), out=a.out)))
