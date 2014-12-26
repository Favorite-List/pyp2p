#! /usr/bin/env python
# -*- coding: utf-8 -*-
#======================================================================
#
# cnetcom.py - udp host basic interface
#
# NOTE:
# ��ַ·�ɼ�������͸����ģ�飬ʹ�� cnetudpģ���е� udpnet�������
# ������͸��·�ɹ��ܣ�Э��������ĵ���
# 
#======================================================================
import sys
import time
import socket
import struct
import collections

import cnetudp


#----------------------------------------------------------------------
# messages header
#----------------------------------------------------------------------
class msghead(object):
	def __init__ (self, suid = 0, skey = 0, duid = 0, dkey = 0, sport = 0, \
					dport = 0, cmd = 0, conv = 0):
		self.suid = suid
		self.skey = skey
		self.duid = duid
		self.dkey = dkey
		self.sport = sport
		self.dport = dport
		self.cmd = cmd
		self.conv = conv
		self.raw = ''
	def __repr__ (self):
		text = '<suid=%d skey=%d duid=%d dkey=%d sport=%d dport=%d cmd=%x '
		text += 'conv=%d>'
		text = text%(self.suid, self.skey, self.duid, self.dkey, \
			self.sport, self.dport, self.cmd, self.conv)
		return text
	def __str__ (self):
		return self.__repr__()
	def marshal (self):
		msg = struct.pack('!llllllll', self.suid, self.skey, self.duid, \
			self.dkey, self.sport, self.dport, self.cmd, self.conv)
		self.raw = msg
		return self.raw
	def unmarshal (self, data):
		if len(data) != 32:
			raise Exception('header size is not 32')
		record = struct.unpack('!llllllll', data)
		self.suid = record[0]
		self.skey = record[1]
		self.duid = record[2]
		self.dkey = record[3]
		self.sport = record[4]
		self.dport = record[5]
		self.cmd = record[6]
		self.conv = record[7]
		self.raw = data
		return self


#----------------------------------------------------------------------
# protocol - Э�鶨��
#----------------------------------------------------------------------
CMD_HELLO	= 0x4001		# punching: ��Է����е�ַ����hello
CMD_HACK	= 0x4002		# punching: �յ�hello����Դ���е�ַ����
CMD_TOUCH	= 0x4003		# punching: �յ�hack�������ͨ�ĵ�ַ����
CMD_TACK	= 0x4004		# punching: �յ�touch�󷵻أ����punching
CMD_PING	= 0x4005		# ��ping
CMD_PACK	= 0x4006		# ping ����

CMD_SYN1	= 0x4010		# connect: step1
CMD_SACK1	= 0x4011		# connect: step2
CMD_SYN2	= 0x4012		# connect: step3
CMD_SACK2	= 0x4013		# connect: step4
CMD_DENY	= 0x4014		# connect: deny
CMD_NOPORT	= 0x4015		# û�иö˿�
CMD_NOCONV	= 0x4016		# û�иûỰ

CMD_DATA	= 0x4020		# data: send
CMD_ACK		= 0x4021		# data: ack
CMD_ALIVE	= 0x4022		# data: keep alive
CMD_ALACK	= 0x4023		# data: alive ack

CMD_FIN1	= 0x4030		# close: fin_1
CMD_FACK1	= 0x4031		# close: fin_ack_1
CMD_FIN2	= 0x4032		# close: fin_2
CMD_FACK2	= 0x4033		# close: fin_ack_2

LOG_HELLO	= 0x01
LOG_HACK	= 0x02
LOG_TOUCH	= 0x04
LOG_TACK	= 0x08
LOG_PUNCHING = (LOG_HELLO | LOG_HACK | LOG_TOUCH | LOG_TACK)

LOG_ROUTE	= 0x10


#----------------------------------------------------------------------
# routing - ·�ɹ�����
# ��ÿ�����������ɵ�ַ����������������ַ��nat��ַ�ȣ�ʹ�õ���˫����ͨ
# ·�кࣺܶ���Է���������������ַ�ģ�ֱ�ӵ��Է�nat��ͨ��stunת����
# ���·�ɹ����������ڹ���ѡ��һ����̨��������õ�ͨ·����punching
# �е��յ�TACK��ʱ�򣬵���routing�����newroute�����punching����֤
# �Ϸ���һ��ͨ·��¼��ȥ������ʱʹ��bestrouteȡ�����·����
#----------------------------------------------------------------------
class routing(object):

	# �����ʼ��
	def __init__ (self, uid, key, linkdesc, current = None, hello = 2.0):
		self.uid = uid
		self.key = key
		self.linkdesc = linkdesc
		self.map = {}
		if not current: 
			current = time.time()
		self.current = current
		self.state = 0
		self.best = None
		self.life = 30
		self.time_hello = current + hello
		self.time_life = current + self.life
		self.time_tick = 0.3
		self.time_slap = current + self.time_tick
		self.time_best = current + hello * 4 + self.time_tick * 2
		self.replys = 0
		self.hello_cnt = 0
		self.hello_max = 100
	
	# �Ƚ�����ͨ·
	def cmproute (self, route1, route2):
		mode1 = route1[2] + route1[4]
		mode2 = route2[2] + route2[4]
		if mode1 < mode2:
			return -100
		elif mode1 > mode2:
			return 100
		type1 = cnetudp.iptype(route1[1][0]) + cnetudp.iptype(route1[3][0])
		type2 = cnetudp.iptype(route1[1][0]) + cnetudp.iptype(route1[3][0])
		if type1 < type2:
			return -10
		elif mode1 > type2:
			return 10
		if route1[0] < route2[0]: 
			return -1
		elif route1[0] == route2[0]:
			return 0
		return 1

	# ����ͨ·
	def newroute (self, rtt, addr1, mode1, addr2, mode2):
		route = (rtt, addr1, mode1, addr2, mode2)
		key = (addr1, mode1, addr2, mode2)
		self.map[key] = min(self.map.get(key, 30), rtt)
		if not self.best:
			self.best = route
		elif self.cmproute(route, self.best) < 0:
			self.best = route
		if (self.state == 0) and (self.best[2] + self.best[4] == 0):
			self.state = 1
		self.replys += 1
		return 0

	# ȡ�����ͨ·
	def bestroute (self):
		if self.state != 1:
			return None
		return self.best
	
	# ����
	def active (self):
		self.time_life = self.current + self.life
	
	# ����״̬������0������������1��hello������2��ping������-1��ùر� -2��ֹ
	def update (self, current = None):
		if not current: 
			current = time.time()
		if current < self.current:
			current = self.current
		self.current = current
		if self.state < 0:
			return -1
		if current > self.time_life:
			oldstate = self.state
			self.state = -1
			if oldstate != 0:
				return -1
			return -2
		if self.state > 0:
			self.time_tick = 20
			if current >= self.time_slap:
				self.time_slap = current + self.time_tick
				return 2
			return 0
		if current >= self.time_slap:
			self.time_slap = current + self.time_tick
			self.hello_cnt += 1
			if self.hello_cnt >= self.hello_max:
				self.state = -1
				return -1
			return 1
		if self.best:
			if self.best[2] + self.best[4] == 0:
				type1 = cnetudp.iptype(self.best[1][0])
				type2 = centudp.iptype(self.best[3][0])
				if type1 < 10 and type2 < 10:
					self.state = 1
			if current >= self.time_hello:
				if self.best[2] + self.best[4] == 0:
					self.state = 1
			if current >= self.time_best:
				self.state = 1
		return 0


#----------------------------------------------------------------------
# hostbase: �������繹������ɵ�ַ̽���뼸���������
#----------------------------------------------------------------------
class hostbase(object):
	
	# �����ʼ��
	def __init__ (self):
		self.network = cnetudp.udpnet()
		self.uid = 0
		self.key = 0
		self.server = None
		self.current = time.time()
		self.sndque = collections.deque()
		self.rcvque = collections.deque()
		self.trace = None
		self.route = {}
		self.badroute = {}
		self.time_route = 0
		self.cnt_port = 0
		self.cnt_conv = 0
		self.logmask = 0
	
	# �����磺ָ��ȫ��Ψһ�� uid�����������룬Ȼ���Ƕ˿ڼ� stun������
	def init (self, uid, passwd, port = 0, server = None):
		self.quit()
		self.uid = int(long(uid) & 0x7fffffff)
		self.key = int(long(passwd) & 0x7fffffff)
		self.network.open(port, server)
		self.current = time.time()
		self.time_route = self.current
		self._cnt_port = (((uid >> 16) + (uid & 0xffff)) % 9 + 1) * 1000
		self._cnt_conv = ((uid >> 16) + (uid & 0xffff)) & 0xffff
		self._cnt_conv += long(time.time() * 1000000) % 1000000
		return 0
	
	# �ر�����
	def quit (self):
		self.network.close()
		self.sndque.clear()
		self.rcvque.clear()
		self.route = {}
		self.badroute = {}
		return 0
	
	# ȡ�ñ�������ĵ�ַ�б�
	def endpoint (self):
		return self.network.ep
	
	# ȡ�õ�ַ������Ϣ���� self.network.ep.marshal����Ϣ
	def linkdesc (self):
		return self.network.linkdesc
	
	# ȡ�ñ��ص�ַ����
	def localhost (self):
		text = '127.0.0.1:%d'%self.network.port
		return text
	
	# ���� UDP���ݣ�Э��ͷ�����ݣ�Զ�̵�ַ���Ƿ�ת��
	def sendudp (self, head, data, remote, forward = 0):
		rawdata = head.marshal() + data
		self.network.send(rawdata, remote, forward)
		return 0
	
	# ���� UDP���ݣ�Э��ͷ�����ݣ�Զ�̵�ַ���Ƿ�ת��
	def recvudp (self):
		head, data, remote, forward = None, '', None, -1
		while 1:
			rawdata, remote, forward = self.network.recv()
			if forward < 0: # û����Ϣ��������
				return None, '', None, -1
			try:	
				head = msghead().unmarshal(rawdata[:32])
				data = rawdata[32:]
				return head, data, remote, forward
			except:			# ��Ϣ���󣬺���
				pass
		return None, '', None, -1
	
	# ���� ping
	def _send_ping (self, duid, dkey, remote, forward):
		head = msghead(self.uid, self.key, duid, dkey, cmd = CMD_PING)
		text = str(self.current)
		self.sendudp(head, text, remote, forward)
		return 0
	
	# ���� ping
	def _recv_ping (self, head, data, remote, forward):
		newhead = msghead(self.uid, self.key, head.suid, head.skey)
		newhead.cmd = CMD_PACK
		self.sendudp(newhead, data, remote, forward)
		return 0
	
	# ���� ping_ack
	def _recv_pack (self, head, data, remote, forward):
		try:
			timestamp = float(data)
		except:
			return -1
		rtt = self.current - timestamp
		ident = head.suid, head.skey
		if ident in self.route:
			self.route[ident].active()
		return 0
	
	# ���ӷ�(addr1, mode1) �����ӷ�(addr2, mode2)
	# cmd_hello = timestamp + addr2 + mode2 + linkdesc1
	def _send_hello (self, duid, dkey, linkdesc):
		head = msghead(self.uid, self.key, duid, dkey, cmd = CMD_HELLO)
		endpoint = cnetudp.endpoint().unmarshal(linkdesc)
		destination = cnetudp.destination(endpoint)
		timestamp = '%.f'%self.current
		linkdesc1 = self.linkdesc()
		if linkdesc[:10] == '127.0.0.1:':
			linkdesc1 = self.localhost()
		for addr2, mode2 in destination:
			text = '%s,%s,%s,'%(timestamp, cnetudp.ep2text(addr2), mode2)
			text += linkdesc1
			if self.trace and (self.logmask & LOG_HELLO):
				self.trace('<hello: %s %d>'%(cnetudp.ep2text(addr2), mode2))
				#print '_send_hello: %s %d'%(addr2, mode2)
			self.sendudp(head, text, addr2, mode2)
		return 0
	
	# ���� hello: ���ݽ��շ��� linkdesc������շ����п���ͨ·���� hack
	def _recv_hello (self, head, data, remote, forward):
		record = data.split(',')
		if len(record) != 4:
			return -1
		timestamp = record[0]
		try:
			addr2 = cnetudp.text2ep(record[1])	# ȡ�ô��������ģ���ַ
			mode2 = int(record[2])				# ȡ�ô��������ģ��Ƿ�ת��
			linkdesc = record[3]
			endpoint = cnetudp.endpoint().unmarshal(linkdesc)
		except:
			return -1
		destination = cnetudp.destination(endpoint, remote, forward)
		if self.trace and (self.logmask & LOG_HELLO):
			self.trace('<recv hello: %s %d %s %d>'%(cnetudp.ep2text(remote),\
				forward, cnetudp.ep2text(addr2), mode2))
		for addr1, mode1 in destination:
			self._send_hack(head.suid, head.skey, timestamp, \
				addr1, mode1, addr2, mode2)
		return 0
	
	# ���ӷ�(addr1, mode1) �����ӷ�(addr2, mode2)
	# cmd_hack = timestamp + addr1 + mode1 + addr2 + mode2
	def _send_hack (self, uid, key, ts, addr1, mode1, addr2, mode2):
		head = msghead(self.uid, self.key, uid, key, cmd = CMD_HACK)
		text = '%s,%s,%s,%s,%s'%(ts, cnetudp.ep2text(addr1), mode1, \
			cnetudp.ep2text(addr2), mode2)
		self.sendudp(head, text, addr1, mode1)
		if self.trace and (self.logmask & LOG_HACK):
			self.trace('<hack %s %d %s %d>'%(cnetudp.ep2text(addr1), mode1,\
				cnetudp.ep2text(addr2), mode2))
			#print '<hack %s %d %s %d>'%(addr1, mode1, addr2, mode2)
		return 0
	
	# ���ӷ�(addr1, mode1) �����ӷ�(addr2, mode2)
	def _recv_hack (self, head, data, remote, forward):
		record = data.split(',')
		if len(record) != 5:
			return -1
		try:
			timestamp = float(record[0])
			addr1 = cnetudp.text2ep(record[1])
			mode1 = int(record[2])
			addr2 = cnetudp.text2ep(record[3])
			mode2 = int(record[4])
		except:
			return -1
		rtt = self.current - timestamp
		rtt = min(30.0, max(0.001, rtt))
		route = [ (rtt, addr1, mode1, addr2, mode2) ]
		if remote != addr2 or forward != mode2:
			route.append((rtt, addr1, mode1, remote, forward))
		timestamp = '%.6f'%self.current
		for rtt, addr1, mode1, addr2, mode2 in route: 
			self._send_touch(head.suid, head.skey, timestamp, 
				addr1, mode1, addr2, mode2)
		if self.trace and (self.logmask & LOG_HACK):
			self.trace('<recv hack: %s %d %s %d>'%(cnetudp.ep2text(addr1), \
				mode1, cnetudp.ep2text(addr2), mode2))
		return 0
	
	# ����touch��Ϣ
	def _send_touch (self, uid, key, ts, addr1, mode1, addr2, mode2):
		head = msghead(self.uid, self.key, uid, key, cmd = CMD_TOUCH)
		text = '%s,%s,%s,%s,%s'%(ts, cnetudp.ep2text(addr1), mode1, \
			cnetudp.ep2text(addr2), mode2)
		self.sendudp(head, text, addr2, mode2)
	
	# ����tack��Ϣ
	def _send_tack (self, uid, key, ts, addr1, mode1, addr2, mode2):
		head = msghead(self.uid, self.key, uid, key, cmd = CMD_TACK)
		text = '%s,%s,%s,%s,%s'%(ts, cnetudp.ep2text(addr1), mode1, \
			cnetudp.ep2text(addr2), mode2)
		self.sendudp(head, text, addr1, mode1)
	
	# ���� touch
	def _recv_touch (self, head, data, remote, forward):
		record = data.split(',')
		if len(record) != 5:
			return -1
		try:
			timestamp = record[0]
			addr1 = cnetudp.text2ep(record[1])
			mode1 = int(record[2])
			addr2 = cnetudp.text2ep(record[3])
			mode2 = int(record[4])
		except:
			return -1
		self._send_tack(head.suid, head.skey, timestamp, \
			addr1, mode1, addr2, mode2)
		return 0
	
	# ���� tack
	def _recv_tack (self, head, data, remote, forward):
		record = data.split(',')
		if len(record) != 5:
			return -1
		try:
			timestamp = float(record[0])
			addr1 = cnetudp.text2ep(record[1])
			mode1 = int(record[2])
			addr2 = cnetudp.text2ep(record[3])
			mode2 = int(record[4])
		except:
			return -1
		rtt = self.current - timestamp
		rtt = min(30.0, max(0.001, rtt))
		if self.trace and (self.logmask & LOG_TACK):
			self.trace('<recv tack: %s %d %s %d>'%(cnetudp.ep2text(addr1), \
				mode1, cnetudp.ep2text(addr2), mode2))
		self._newroute(head.suid, head.skey, rtt, addr1, mode1, addr2, mode2)
		return 0
	
	# ���һ����·�������ӷ��յ� tack�Ժ����
	def _newroute (self, uid, key, rtt, addr1, mode1, addr2, mode2):
		ident = (uid, key)
		#print '[PATH] %.3f %s %d %s %d'%(rtt, addr1, mode1, addr2, mode2)
		if self.trace and (self.logmask & LOG_ROUTE):
			self.trace('<newroute: %s %d %s %d>'%(cnetudp.ep2text(addr1), \
				mode1, cnetudp.ep2text(addr2), mode2))
		if ident in self.route:
			route = self.route[ident]
			route.active()
			route.newroute(rtt, addr1, mode1, addr2, mode2)
			route.update(self.current)
		return 0
	
	# ȡ�����·�����Է���uid, key�Լ� linkdesc
	def bestroute (self, uid, key, linkdesc):
		ident = (uid, key)
		if ident in self.badroute:
			if self.current - self.badroute[ident] < 25:
				return None
			del self.badroute[ident]
		if ident in self.route:
			route = self.route[ident]
			if route.linkdesc != linkdesc:	# ��Ҫ�������γ�ʼ����������
				del self.route[ident]
		if not ident in self.route:		# �Զ����� routing���󲢷��� hello
			route = routing(uid, key, linkdesc, self.current)
			self.route[ident] = route
			self._send_hello(uid, key, linkdesc)
			return None
		route = self.route[ident]
		best = route.bestroute()
		return best
	
	# ����·������Ҫ����ɾ��
	def active (self, uid, key):
		ident = (uid, key)
		if ident in self.route:
			route = self.route[ident]
			route.active()
		return 0
	
	# ɾ��·�����´���������
	def delroute (self, uid, key):
		ident = (uid, key)
		if ident in self.route:
			del self.route[ident]
		return 0
	
	# ·�ɸ��£�ɨ����ڵ�·�ɲ����ʵ�ʱ���ظ����� hello�� ping����ɾ
	def _route_update (self):
		for ident, route in self.route.items():
			code = route.update(self.current)
			if code == 1:
				self._send_hello(route.uid, route.key, route.linkdesc)
			elif code == -1:
				del self.route[ident]
			elif code == -2:
				del self.route[ident]
				self.badroute[ident] = self.local
		return 0
	
	# ��Ϣ�ַ�������·�ɼ���͸�����Ϣ��������Ϣ���� _process����
	def _dispatch (self, head, data, remote, forward):
		cmd = head.cmd
		if cmd == CMD_HELLO:
			self._recv_hello(head, data, remote, forward)
		elif cmd == CMD_HACK:
			self._recv_hack(head, data, remote, forward)
		elif cmd == CMD_TOUCH:
			self._recv_touch(head, data, remote, forward)
		elif cmd == CMD_TACK:
			self._recv_tack(head, data, remote, forward)
		elif cmd == CMD_PING:
			self._recv_ping(head, data, remote, forward)
		elif cmd == CMD_PACK:
			self._recv_pack(head, data, remote, forward)
		else:
			self._process (head, data, remote, forward)
		return 0
	
	# ����·�ɼ���͸������Ϣ���������Լ�ʵ��
	def _process (self, head, data, remote, forward):
		return 0

	# ����һ���µĶ˿ں�
	def _gen_port (self):
		self._cnt_port += 1
		if self._cnt_port >= 0x7fff: 
			self._cnt_port = 0
		return self._cnt_port
	
	# ����һ���µĻỰ��
	def _gen_conv (self):
		self._cnt_conv += 1 + int(self.current) % 10
		if self._cnt_conv >= 0x7fffffff:
			self._cnt_conv = 1 + int(self.current) % 10
		return self._cnt_conv
	
	# �������� pingֵȡ��
	def pingsvr (self):
		if self.network.state != 1:
			return -1.0
		return self.network.pingsvr * 0.001

	# ����״̬
	def update (self):
		self.current = time.time()
		self.network.update()
		while 1:
			head, data, remote, forward = self.recvudp()
			if forward < 0: break
			if head.duid == self.uid and head.dkey == self.key:
				self._dispatch (head, data, remote, forward)
		if self.current > self.time_route:
			self.time_route = self.current + 0.1
			self._route_update()
		return 0



#----------------------------------------------------------------------
# route2text: ͨ·ת��Ϊ�ַ���
#----------------------------------------------------------------------
def route2text(rtt, addr1, mode1, addr2, mode2):
	text = '%.06f,%s,%d,%s,%d'%(rtt, cnetudp.ep2text(addr1), mode1, \
		cnetudp.ep2text(addr2), mode2)
	return text

#----------------------------------------------------------------------
# route2text: �ַ���ת��Ϊͨ·
#----------------------------------------------------------------------
def text2route(text):
	text.strip(' ')
	record = text.split(',')
	if len(record) != 5:
		return None
	try:
		rtt = float(record[0])
		addr1 = cnetudp.text2ep(record[1])
		mode1 = int(record[2])
		addr2 = cnetudp.text2ep(record[3])
		mode2 = int(record[4])
	except:
		return None
	return rtt, addr1, mode1, addr2, mode2

#----------------------------------------------------------------------
# plog: �����־
#----------------------------------------------------------------------
def plog_raw(prefix, mode, *args):
	head = time.strftime('%Y%m%d %H:%M:%S', time.localtime())
	text = ' '.join([ str(n) for n in args ])
	line = '[%s] %s'%(head, text)
	if (mode & 1) != 0:
		current = time.strftime('%Y%m%d', time.localtime())
		logfile = sys.modules[__name__].__dict__.get('logfile', None)
		logtime = sys.modules[__name__].__dict__.get('logtime', '')
		if current != logtime:
			logtime = current
			if logfile: logfile.close()
			logfile = None
		if logfile == None:
			logfile = open('%s%s.log'%(prefix, current), 'a')
		sys.modules[__name__].__dict__['logtime'] = logtime
		sys.modules[__name__].__dict__['logfile'] = logfile
		logfile.write(line + '\n')
		logfile.flush()
	if (mode & 2) != 0:
		sys.stdout.write(line + '\n')
	if (mode & 4) != 0:
		sys.stderr.write(line + '\n')
	return 0

# �յ���־����ӿ�
def plog_none(*args):
	pass

# ������ļ���'n20xxMMDD.log'��
def plog_file(*args):
	plog_raw('n', 1, *args)

# �������׼���
def plog_stdout(*args):
	plog_raw('n', 2, *args)

# �������׼����
def plog_stderr(*args):
	plog_raw('n', 4, *args)

# ������ļ�����׼���
def plog_file_and_stdout(*args):
	plog_raw('n', 3, *args)

# ������ļ�����׼����
def plog_file_and_stderr(*args):
	plog_raw('n', 5, *args)

# ��־�ӿں���ָ�룺�ⲿ���� plogд��־
plog = plog_none


#----------------------------------------------------------------------
# ��Ϣ��ŷ���
#----------------------------------------------------------------------
_cmd_names = {}

for key, value in sys.modules[__name__].__dict__.items():
	if key[:4] == 'CMD_':
		_cmd_names[value] = key

cmdname = lambda cmd: _cmd_names.get(cmd, 'CMD_%x'%cmd)

'''
-----------------------------------------------------------------------
                             ̽��Э��
-----------------------------------------------------------------------
CMD_HELLO: timestamp, addr2, mode2, linkdesc
CMD_HACK:  timestamp, addr1, mode1, addr2, mode2
CMD_TOUCH: timestamp, addr1, mode1, addr2, mode2
CMD_TACK   timestamp, addr1, mode1, addr2, mode2

Զ�̵�ַ��һ��Զ�̵�ַ�� addr(ip,�˿�) mode(ģʽ���Ƿ�ת��) ���������
��ַ��ţ�addr1, mode1Ϊ����hello����ַ��addr2, mode2Ϊ����hello����ַ

   ���ӷ�(���1)              ���շ�(���2)
   ------------------------------------------
    CMD_HELLO      --------> (�����ɵ�ַ����)
	               -------->
	�����ɵ�ַ���� <-------- CMD_HACK
                   <--------
	CMD_TOUCH      --------> 
	               <-------- CMD_TACK
	����ͨ·

���ӷ���̽�ⷽ������ظ����� CMD_HELLO��ֱ���յ�һ�������� CMD_TACK��
���ߴﵽһ��ʱ�䣨����10�룩��

1. ���Ӷ˷���CMD_HELLO���������Ӷ˵�ÿ�������ӵ�ַ�������nat��ַ�Ļ�
Ҳ��ʹ��ֱ�ӷ��ͺ�stunת�� CMD_HELLO���� nat��ַ��

CMD_HELLO:
    timestamp    ���͵�ʱ��
    addr2        �����ӷ���Ŀ���ַ
    mode2        �����ӷ������ӷ�ʽ���Ƿ�ת��
    linkdesc     ���ӷ��ĵ�ַ����

2. �����Ӷ��յ�CMD_HELLO�Ժ󣬰������ӷ��� linkdesc�õ����ӷ����п���
�ķ���ͨ·������������ַ���� nat��ַ��������ÿ��ͨ·���ظ������ӷ�
CMD_HACK����� linkdesc�������ӷ��� nat��ַ����ʹ��ֱ�ӷ����� stunת��
���ַ����������� CMD_HACK�����ӷ�����󣬻�Ҫ�� ���յ� CMD_HELLOʱȡ��
��Զ�̵�ַ������������δ֪����û�� linkdesc������������һ�� CMD_HACK��

CMD_HACK:
    timestamp    ԭ·���ص�ʱ��
    addr1        ���ӷ���ַ
    mode1        ���ӷ���ʽ
    addr2        �����ӷ���Ŀ���ַ
    mode2        �����ӷ������ӷ�ʽ

3. �����ӷ����յ�CMD_HACK��ʱ�����ͳ�ƣ��ռ���
   (rtt, addr1, mode1, addr2, mode2) Ϊ��һ������ͨ·
   (rtt, addr1, mode1, �յ�CMD_HACK��Զ�̵�ַ������) Ϊ�ڶ�������ͨ·
   ��Ϊ�ӱ����Ӷ˵����Ӷ˿��ܴ���δ֪�ĳ��ڣ������еڶ���ͨ·�Ĵ���
   Ȼ��������ͨ·�ֱ��� CMD_TOUCH�ٴ���֤��

CMD_TOUCH:
    timestamp    ԭ·���ص�ʱ��
    addr1        ���ӷ���ַ
    mode1        ���ӷ���ʽ
    addr2        �����ӷ���Ŀ���ַ
    mode2        �����ӷ������ӷ�ʽ

4. �����ӷ��յ�cmd_touch�󣬴�addr1, mode1λ�÷��� cmd_tack

CMD_TACK:
    timestamp    ԭ·���ص�ʱ��
    addr1        ���ӷ���ַ
    mode1        ���ӷ���ʽ
    addr2        �����ӷ���Ŀ���ַ
    mode2        �����ӷ������ӷ�ʽ

5. �յ�cmd_tack�󣬼�¼��ͳ��ͨ·�� 
   (rtt, addr1, mode1, addr2, mode2)
'''

#----------------------------------------------------------------------
# testing case
#----------------------------------------------------------------------
if __name__ == '__main__':
	def wait(*args):
		timeout = time.time() + 4
		while 1:
			time.sleep(0.1)
			count = 0
			for host in args:
				host.update()
				if host.network.state == 1:
					count += 1
			if count == len(args): 
				break
			if time.time() > timeout: break
		return 0
	def server(*args):
		while 1:
			time.sleep(0.001)
			for host in args:
				host.update()
	def test1():
		host1 = hostbase()
		host2 = hostbase()
		host1.trace = plog_stdout
		host1.init(20081308012, 12345, 0, ('218.107.55.250', 2009))
		host2.init(20081308013, 12345, 0, ('218.107.55.250', 2009))
		wait(host1, host2)
		linkdesc = host2.localhost()
		#linkdesc = host2.linkdesc()
		print linkdesc
		timeslap = time.time()
		while 1:
			time.sleep(0.001)
			host1.update()
			host2.update()
			if time.time() >= timeslap:
				timeslap = time.time() + 2
				result = host1.bestroute(host2.uid, host2.key, linkdesc)
				print result
				if result:
					#host1.delroute(host2.uid, host2.key)
					pass
				print host1.pingsvr()
				host1.active(host2.uid, host2.key)
		return 0
	
	def test2():
		host1 = hostbase()
		host1.init(20013070, 222222, 0, ('218.107.55.250', 2009))
		wait(host1)
		print 'linkdesc:',
		host1.update()
		linkdesc = raw_input()
		host1.update()
		timeslap = time.time() + 1
		timereport = time.time() + 5
		while 1:
			time.sleep(0.1)
			host1.update()
			if time.time() > timeslap:
				timeslap = time.time() + 2
				print host1.bestroute(20013080, 111111, linkdesc)
				host1.active(20013080, 111111)
			if time.time() > timereport:
				timereport = time.time() + 5
				print host1.network.statistic_report()
				print 'svrping', host1.pingsvr()
	
	def test3():
		host1 = hostbase()
		host1.init(20013080, 111111, 0, ('218.107.55.250', 2009))
		wait(host1)
		print host1.uid, host1.key, host1.linkdesc()
		for i in xrange(10):
			print host1._gen_port(), host1._gen_conv()
		server(host1)
	
	def test4():
		rtt = 0.2
		addr1 = ('192.168.10.214', 100)
		mode1 = 0
		addr2 = ('202.108.8.40', 200)
		mode2 = 1
		text = route2text(rtt, addr1, mode1, addr2, mode2)
		print text
		route = text2route(text)
		print route

	plog('hahahahah')
	test1()
	# cnetgem.py cnetdew cnetlax.py

