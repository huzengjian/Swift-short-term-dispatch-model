
from gurobipy import *
import msvcrt
import numpy as np
import pandas as pd

def Vol2Fb(vol):
    return 704.4 + 11.325 * np.sqrt(vol - 90.0)

def Fb2Vol(fb):
    return np.power((fb - 704.4)/11.325, 2) + 90.0

def Vol2Hk(vol):
	return 14.36 + 0.907 * np.sqrt(vol - 90.0)
	
days = 30
tailwater = 600
baseHK = 35

minInf = 20
maxInf = 50

minPrice = 30
maxPrice = 50

init_fb = 960 # fb range [900-1000]

M = 100000
minVol = 389
maxVol = 755 #volume range (389 - 755)
maxHK = Vol2Hk(maxVol)
minHK = Vol2Hk(minVol)
minQo = 20
maxQo = 80
maxQoRamp = 20 #max discharge ramp
maxSpillPct = 0.5

genPenalty = 10
nApprox = 50

vol = {}
qo = {}
qp = {}
qs = {}
#fb = {}
#gn = {}
hk = {}
deviation = {}
u = {}
v = {}
sqrt_vol = {}

lmda1 = {}
lmda2 = {}


	
def read_schedule_value(s):
    return m.getAttr('x', s)
	
	
def printSolution(m, prices,inflows, gen_targets, out_file_name):
	avg_price = np.mean(prices)
	if m.status != GRB.status.INFEASIBLE:
		print('\nObjective by Gurobi: %g' % m.objVal)
		schedules = {}
		for name, var in zip(['Volume','Discharge','TurbineFlow','Spill','H/K'], [vol, qo, qp, qs,hk]):
			schedules[name] = read_schedule_value(var)
		schedules['Prices'] = prices
		schedules['Inflows'] = inflows
		schedules['Gen Targets'] = gen_targets

		qp_schedule = read_schedule_value(qp)
		hk_schedule = read_schedule_value(hk)
		vol_schedule = read_schedule_value(vol)
		schedules['Generation'] = [t * h for (t, h) in zip(qp_schedule.values(), hk_schedule.values())]
		schedules['Revenue'] = [g * p for (g,p) in zip(schedules['Generation'], prices)]
		schedules['Forebay'] = [Vol2Fb(volume) for volume in vol_schedule.values()]
		schedules['H/K Trueup'] = [Vol2Hk(volume) for volume in vol_schedule.values()]
		
		total_rev = sum(schedules['Revenue'])
		print "Total Revenue = {0}".format(total_rev)
		water_val = avg_price*schedules['Volume'][days-1]*baseHK
		print "Water Value = {0}($/MW) * {1}(kcfs) * {2}(MW/kcfs) = {3}($)".format(avg_price, schedules['Volume'][days-1], baseHK, water_val)
		print "Actual Objective = {0}".format(total_rev+water_val)

		df = pd.DataFrame(index = xrange(days))
		for key in schedules.keys():
			df[key] = pd.Series(schedules[key], index=df.index)
		df.to_csv(out_file_name)
		print "Result Exported."
	else:
		print 'Fail to find feasible solution, please check your inputs!'

def build_model(days, init_fb, prices, inflows, gen_targets = [], gen_penalties = [], quad = False, water_val = False):
	#print gen_targets
	target = len(gen_targets) > 0
	m = Model("swift")
	avg_price = np.mean(prices)
	for i in range(days):
		vol[i] = m.addVar(lb=minVol, ub=maxVol, obj = (0 if i < days - 1 and water_val else (avg_price * baseHK)), name='vol_{i}'.format(i = i))
		qo[i] = m.addVar(lb=minQo, ub=maxQo, name='qo_{i}'.format(i = i))
		qp[i] = m.addVar(lb=minQo, ub=maxQo, obj = 0 if quad else (prices[i] * baseHK), name='qp_{i}'.format(i = i))
		qs[i] = m.addVar(lb=0, ub=maxQo, name='qs_{i}'.format(i = i))
		hk[i] = m.addVar(lb=minHK, ub=maxHK, name='hk_{i}'.format(i = i))
		#fb[i] = m.addVar(lb=Vol2Fb(minVol), ub=Vol2Fb(maxVol), name='fb_{i}'.format(i = i))
		sqrt_vol[i] = m.addVar(lb=0, ub=M, name='sqrt_vol_{i}'.format(i = i))
		if(quad):
			u[i] = m.addVar(lb = -M, ub = M, name = 'u_{i}'.format(i = i))
			v[i] = m.addVar(lb = -M, ub = M, name = 'v_{i}'.format(i = i))
		#gn[i] = m.addVar(lb=0, ub=maxQo * maxHK, obj = prices[i], name='gn_{i}'.format(i = i))

	m.update()
	m.addConstr(vol[0] == Fb2Vol(init_fb)) # initial volume

	uanchors = np.linspace(minHK/2, (maxHK + maxQo)/2, nApprox)
	vanchors = np.linspace(-maxHK/2, (maxQo - minHK)/2, nApprox)
	hkanchors = np.linspace(minHK, maxHK, nApprox)
	qpanchors = np.linspace(0, maxQo, nApprox)
	
	for i in xrange(days - 1):
		m.addConstr(vol[i+1] == vol[i] - qo[i] +  inflows[i].item(), 'volume_{i}'.format(i=i)) # water balance constraint
		m.addConstr(qo[i+1] <= qo[i] + maxQoRamp, 'discharge_ramp_upper_{i}'.format(i=i)) # Discharge <= Discharge(t) + Discharge Ramp
		m.addConstr(qo[i+1] >= qo[i] - maxQoRamp, 'discharge_ramp_lower_{i}'.format(i=i)) # Discharge >= Discharge(t) - Discharge Ramp
	for i in xrange(days):
		m.addConstr(qo[i] == qp[i] + qs[i],'discharge_{i}'.format(i=i)) # Discharge = Turb Flow + Spill
		m.addConstr(qs[i] <= maxSpillPct * qo[i], 'spill_{i}'.format(i=i)) # Spill <= maxSpillPct * Discharge
		m.addConstr(hk[i] <= 14.36 + 0.907 * sqrt_vol[i], 'hk_vol_{i}'.format(i=i)) #hk =  14.36 + 0.907 * \sqrt(vol - 90)
		m.addQConstr(sqrt_vol[i]*sqrt_vol[i] + 90.0 <= vol[i], 'sqrt_of_volume_{i}'.format(i=i))
		if(quad):
			m.addConstr(u[i] == (qp[i] + hk[i])/2)
			m.addConstr(v[i] == (qp[i] - hk[i])/2)
			if(target):
				penalty = gen_penalties[i].item()
				target = gen_targets[i].item()
				m.setPWLObj(u[i], uanchors, prices[i] * np.power(uanchors, 2) + penalty * (-4.0/3.0 * np.power(uanchors, 4) + 2 * target * np.power(uanchors, 2)))
				m.setPWLObj(v[i], vanchors, -prices[i] * np.power(vanchors, 2) + penalty * (-4.0/3.0 * np.power(vanchors, 4) - 2 * target * np.power(vanchors, 2)))
				m.setPWLObj(qp[i], qpanchors, penalty * np.power(qpanchors, 4) / 6.0)
				m.setPWLObj(hk[i], hkanchors, penalty * (np.power(hkanchors, 4) / 6.0 - target*target))
			else:
				#PWL formulation
				m.setPWLObj(u[i], uanchors, prices[i] * np.power(uanchors, 2))
				m.setPWLObj(v[i], vanchors, -prices[i] * np.power(vanchors, 2))

	m.modelSense = GRB.MAXIMIZE
	#m.setObjective(quicksum(qp[i] * hk[i] * prices[i].item() for i in xrange(days)))
	#m.setObjective(quicksum(0.5 * (u[i] * u[i] - v[i] * v[i]) * prices[i].item() for i in xrange(days))) # doesn't work as the Object Q matrix is not PSD
	
	m.update()
	return m

prices = np.random.uniform(minPrice, maxPrice, [days])
inflows = np.random.uniform(minInf, maxInf, [days])
gen_targets = np.random.uniform(800, 1500, [days])
gen_penalties = np.random.uniform(genPenalty, genPenalty, [days])

try:			
	m = build_model(days = days, prices = prices, init_fb = init_fb, inflows = inflows, gen_targets = gen_targets, gen_penalties = gen_penalties, quad = True, water_val = True)
	m.optimize()
	printSolution(m, prices = prices, inflows = inflows, gen_targets = gen_targets, out_file_name = "swift_quad.csv")

	m = build_model(days = days, prices = prices, init_fb = init_fb, inflows = inflows, gen_targets = gen_targets, gen_penalties = gen_penalties, quad = False, water_val = True)
	m.optimize()
	printSolution(m, prices = prices, inflows = inflows, gen_targets = gen_targets, out_file_name = "swift_linear.csv")
except GurobiError as e:
	print "Unexpected error:", sys.exc_info()[0], e
	m.write('error_model.mps')


"""	
	#print_lambda("lambda1", lmda1)
	#print_lambda("lambda2", lmda2)

	#print_schedule('Volume', vol)
	#print_schedule('Forebay', fb)
	#print_schedule('Discharge', qo)
	#print_schedule('TurbineFlow', qp)
    #print_schedule('H/K', hk)
	#print_schedule_value('Generation', gn_schedule)

	def print_schedule_value(name, sx):
    print '\n', name
    for i in xrange(days):
        print('%g' % (sx[i]))
    msvcrt.getch()
	
def print_lambda(name, lmda):
    print '\n', name
    lmdax = m.getAttr('x', lmda)
    for i in xrange(days):
		for j in xrange(nApprox):
			print('%g' % (lmdax[i,j]))
			print('\n')
		msvcrt.getch()	

def print_schedule(name, s):
    print_schedule_value(name, read_schedule_value(s))

	def gen_rand_price_curve(days):
	prices =[]
	for i in xrange(days):
		llh = i%24 < 6 or i%24 > 21
		basePrice = llhPrice if llh else hlhPrice
		prices.append(np.random.uniform(basePrice - priceVar, basePrice + priceVar))
	return prices

"""