
from gurobipy import *
import msvcrt
import numpy as np
import pandas as pd

def Vol2Fb(vol):
    return 704.23078 + 11.32277 * np.sqrt(vol - 89.96) # fb range [900,1000]

def Fb2Vol(fb):
    return 0.0078 *  fb * fb - 10.986 * fb + 3958.3 # vol range [388.9,772.3]

def Vol2Hk(vol):
	return 14.36 + 0.907 * np.sqrt(vol - 89.96)
	
days = 90
tailwater = 600
baseHK = 35

minInf = 2
maxInf = 10

minPrice = 30
maxPrice = 50

init_fb = 936

M = 100000
minVol = 388.9
maxVol = 772.3 #volume range [388.9,772.3]
maxHK = Vol2Hk(maxVol)
minHK = Vol2Hk(minVol)
minQo = 2
maxQo = 8
maxQoRamp = 2 #max discharge ramp
maxSpillPct = 1

genPenalty = 10
nApprox = 10

vol = {}
qo = {}
qp = {}
qs = {}
#fb = {}
#gn = {}
hk = {}
#deviation = {}
u = {}
v = {}
sqrt_vol = {}

def read_schedule_value(s):
    return m.getAttr('x', s)
	
	
def printSolution(m, prices, inflows, gen_targets, fb_targets, out_file_name):
	avg_price = np.mean(prices)
	if m.status != GRB.status.INFEASIBLE:
		print('\nObjective by Gurobi: %g' % m.objVal)
		schedules = {}
		for name, var in zip(['Volume','Discharge','TurbineFlow','Spill','H/K'], [vol, qo, qp, qs,hk]):
			schedules[name] = read_schedule_value(var)
		schedules['Prices'] = prices
		schedules['Inflows'] = inflows
		schedules['Gen Targets'] = gen_targets
		schedules['Fb Targets'] = fb_targets

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

def build_model(days, init_fb, prices, inflows, gen_targets = [], gen_penalties = [], fb_targets = [], quad = False, water_val = False):
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

	ucoords = np.linspace(minHK/2, (maxHK + maxQo)/2, nApprox)
	vcoords = np.linspace(-maxHK/2, (maxQo - minHK)/2, nApprox)
	hkcoords = np.linspace(minHK, maxHK, nApprox)
	qpcoords = np.linspace(0, maxQo, nApprox)
	
	for i in xrange(days - 1):
		m.addConstr(vol[i+1] == vol[i] - qo[i] +  inflows[i].item(), 'volume_{i}'.format(i=i)) # water balance constraint
		m.addConstr(qo[i+1] <= qo[i] + maxQoRamp, 'discharge_ramp_upper_{i}'.format(i=i)) # Discharge <= Discharge(t) + Discharge Ramp
		m.addConstr(qo[i+1] >= qo[i] - maxQoRamp, 'discharge_ramp_lower_{i}'.format(i=i)) # Discharge >= Discharge(t) - Discharge Ramp
	for i in xrange(days):
		m.addConstr(qo[i] == qp[i] + qs[i],'discharge_{i}'.format(i=i)) # Discharge = Turb Flow + Spill
		m.addConstr(qs[i] <= maxSpillPct * qo[i], 'spill_{i}'.format(i=i)) # Spill <= maxSpillPct * Discharge
		m.addConstr(hk[i] <= 14.36 + 0.907 * sqrt_vol[i], 'hk_vol_{i}'.format(i=i)) #hk =  14.36 + 0.907 * \sqrt(vol - 89.96)
		m.addQConstr(sqrt_vol[i]*sqrt_vol[i] + 89.96 <= vol[i], 'sqrt_of_volume_{i}'.format(i=i))
		if(len(fb_targets) > 0 and fb_targets[i] != 0): # 0 means not enforced
			m.addConstr(vol[i] == Fb2Vol(fb_targets[i]), 'fb_target_{i}'.format(i=i))
		if(quad):
			m.addConstr(u[i] == (qp[i] + hk[i])/2)
			m.addConstr(v[i] == (qp[i] - hk[i])/2)
			if(len(gen_targets) > 0):
				penalty = gen_penalties[i].item()
				target = gen_targets[i].item()
				m.setPWLObj(u[i], ucoords, prices[i] * np.power(ucoords, 2) + penalty * (-4.0/3.0 * np.power(ucoords, 4) + 2 * target * np.power(ucoords, 2)))
				m.setPWLObj(v[i], vcoords, -prices[i] * np.power(vcoords, 2) + penalty * (-4.0/3.0 * np.power(vcoords, 4) - 2 * target * np.power(vcoords, 2)))
				m.setPWLObj(qp[i], qpcoords, penalty * np.power(qpcoords, 4) / 6.0)
				m.setPWLObj(hk[i], hkcoords, penalty * (np.power(hkcoords, 4) / 6.0 - target*target))
			else:
				#PWL formulation
				m.setPWLObj(u[i], ucoords, prices[i] * np.power(ucoords, 2))
				m.setPWLObj(v[i], vcoords, -prices[i] * np.power(vcoords, 2))

	m.modelSense = GRB.MAXIMIZE
	#m.setObjective(quicksum((u[i] * u[i] - v[i] * v[i]) * prices[i].item() for i in xrange(days)))
	m.update()
	return m

prices = np.random.uniform(minPrice, maxPrice, [days])
inflows = np.random.uniform(minInf, maxInf, [days])
gen_targets = np.random.uniform(100, 200, [days])
gen_penalties = np.random.uniform(genPenalty, genPenalty, [days])
fb_targets = [0] * days
fb_targets[days/2] = 925
fb_targets[days-1] = 965

try:			
	m = build_model(
		days = days, 
		prices = prices, 
		init_fb = init_fb, 
		inflows = inflows, 
		#gen_targets = gen_targets, 
		#gen_penalties = gen_penalties, 
		fb_targets = fb_targets, 
		quad = True, 
		water_val = True)
	m.optimize()
	printSolution(m, prices = prices, inflows = inflows, gen_targets = gen_targets, fb_targets = fb_targets, out_file_name = "swift_quad.csv")

	#m = build_model(days = days, prices = prices, init_fb = init_fb, inflows = inflows, gen_targets = gen_targets, gen_penalties = gen_penalties, quad = False, water_val = True)
	#m.optimize()
	#printSolution(m, prices = prices, inflows = inflows, gen_targets = gen_targets, out_file_name = "swift_linear.csv")
except GurobiError as e:
	print "Unexpected error:", sys.exc_info()[0], e
	m.write('error_model.mps')


"""	
	#m.setObjective(quicksum((u[i] * u[i] - v[i] * v[i]) * prices[i].item() for i in xrange(days)))
	#m.setObjective(quicksum(0.5 * (u[i] * u[i] - v[i] * v[i]) * prices[i].item() for i in xrange(days))) # doesn't work as the Object Q matrix is not PSD

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

if(sos2):
				#SOS2 formulation
				m.addConstr(u[i] == quicksum([lmda1[i,j] * x for x,j in zip(uanchors, xrange(nApprox))]))
				m.addSOS(GRB.SOS_TYPE2, [lmda1[i,j] for j in xrange(nApprox)]) # \sum{\lambda(i)} == 1. exactly two nonzeros, and they must be adjacent
				m.addConstr(quicksum([lmda1[i,j] for j in xrange(nApprox)]) == 1)
				m.addConstr(v[i] == quicksum([lmda2[i,j] * x for x,j in zip(vanchors, xrange(nApprox))]))
				m.addSOS(GRB.SOS_TYPE2, [lmda2[i,j] for j in xrange(nApprox)])
				m.addConstr(quicksum([lmda2[i,j] for j in xrange(nApprox)]) == 1)	

				
	if(sos2):
		obj =  quicksum(prices[i] *(quicksum([lmda1[i,j] * x * x for x,j in zip(uanchors, xrange(nApprox))]) -
										   quicksum([lmda2[i,j] * x * x for x,j in zip(vanchors, xrange(nApprox))])) for i in xrange(hours))				
"""