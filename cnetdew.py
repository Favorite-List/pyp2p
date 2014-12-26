#! /usr/bin/env python
# -*- coding: utf-8 -*-
#======================================================================
#
# cnetdew.py - 
#
# NOTE:
# for more information, please see the readme file.
# 
#======================================================================
import sys
import time
import socket
import struct
import collections

import cnetudp
import cnetcom
import cnetdat

from cnetcom import CMD_SYN1, CMD_SYN2, CMD_SACK1, CMD_SACK2, CMD_DENY
from cnetcom import CMD_DATA, CMD_ACK, CMD_ALIVE, CMD_NOPORT, CMD_NOCONV
from cnetcom import CMD_ALACK, CMD_FIN1, CMD_FACK1, CMD_FIN2, CMD_FACK2


#----------------------------------------------------------------------
# simple reliable
#----------------------------------------------------------------------
class nprotocol(cnetdat.reliable):
	def __init__ (self, connection):
		self.connection = connection
		super(nprotocol, self).__init__ (connection.conv, 1400, \
			connection.current, connection.sport)
	def output (self, data):
		if self.connection != None:
			self.connection.send(CMD_DATA, data)
			

#----------------------------------------------------------------------
# connection state
#----------------------------------------------------------------------
TYPE_CONNECTOR		= 0		# �������ͣ�������
TYPE_LISTENER		= 1		# �������ͣ���������

# ������״̬��������������20��
STATE_LISTEN		= 0		# ��ʼ״̬
STATE_C_ROUTING		= 1		# �����ߣ�����͸��ȡ�����·��
STATE_C_SYN1		= 2		# �����ߣ���ͣ����syn1
STATE_L_SYN1		= 3		# �����ߣ��ȴ�syn1������sack1
STATE_C_SYN2		= 4		# �����ߣ���ͣ�ķ���syn2
STATE_L_SYN2		= 5		# �����ߣ��ȴ�syn2������sack2
STATE_READY			= 6		# ׼������״̬���Ѿ������ϣ��ȴ��²�Э�����ӣ�

# �Ự��״̬���Ự����keepalive
STATE_CONNECTED		= 7		# ���ӳɹ�
STATE_CLOSED		= 8		# �Ͽ�����

# ������״̬��������������10��


TIME_CONNECTING		= 20	# �����ڳ�ʱ��20��
TIME_CLOSING		= 10	# �Ͽ��ڳ�ʱ��10��
TIME_KEEPALIVE		= 3		# �����ڳ�ʱ��30��


#----------------------------------------------------------------------
# connection - ���Ӽ���Э��
#----------------------------------------------------------------------
class connection(object):
	
	def __init__ (self, type, host, port, duid, dkey, conv, linkdesc = ''):
		self.host = host
		self.sport = port
		self.dport = 0
		self.duid = duid
		self.dkey = dkey
		self.conv = conv
		self.linkdesc = linkdesc
		self.current = host.current
		self.state = STATE_LISTEN
		self.type = type				# 0�����ӷ� 1�Ǳ����ӷ�
		self.establish = 0				# �Ƿ�������
		self.route = None				# ·����Ϣ
		self.dstaddr = None				# Զ�˵�ַ��(ip, port)
		self.dstmode = 0				# Զ�˷��ͷ�ʽ���Ƿ�ת��
		self.head = cnetcom.msghead()
		self.head.suid = self.host.uid
		self.head.skey = self.host.key
		self.head.duid = self.duid
		self.head.dkey = self.dkey
		self.head.sport = self.sport
		self.head.conv = self.conv
		self.head.cmd = 0
		if self.type == TYPE_CONNECTOR: self.state = STATE_C_ROUTING
		else: self.state = STATE_L_SYN1
		self.timeout = cnetudp.timeout(self.current)
		self.time_life = self.current + TIME_CONNECTING		# ��������������
		self.time_plus = self.current + 0.1					# ������ʱ
		self.time_mini = self.current
		self.time_rtt = 1.0
		self.time_alive = self.current
		self.accepted = 0
		self.snd_seq = 0
		self.rcv_seq = 0
		self.limit = 1024				# ��Ϣ���泤��
		self.sendque = collections.deque()
		self.recvque = collections.deque()
		self.protocol = nprotocol(self)
		self.inited = 0

	def close (self):
		self.host = None
		self.linkdesc = ''
		self.endpoint = None
		self.head = None
		self.route = None
		self.state = -1
		self.establish = -1
		self.sendque.clear()
		self.recvque.clear()
		self.sendque = None
		self.recvque = None
	
	def send (self, cmd, data):
		head = self.head
		head.cmd = cmd
		if not self.dstaddr:
			return -1
		self.host.sendudp(head, data, self.dstaddr, self.dstmode)
		return 0
	
	def timeout_reset (self):
		self.timeout.reset(self.current)
	
	def timeout_check (self):
		return self.timeout.check(self.current)
	
	def isalive (self):
		if self.establish < 0:
			return False
		return True
	
	def __len__ (self):
		return len(self.recvque)
	
	def log (self, *args):
		self.host.log('[%d]'%self.sport, *args)
		return 0
	
	# ��������
	def _try_connecting (self):
		if self.current < self.time_plus:
			return 0
		self.time_plus = self.current + 0.1
		if self.current >= self.time_life:
			self.establish = -1
			return -1
		state = self.state
		if state == STATE_C_ROUTING:		# ���ڲ���·�ɼ� punching
			duid, dkey, linkdesc = self.duid, self.dkey, self.linkdesc
			self.route = self.host.bestroute(duid, dkey, linkdesc)
			if self.inited == 0:
				self.inited = 1
				self.log('routing duid=%d dkey=%d'%(duid, dkey))
				#self.log('linkdesc="%s"'%self.linkdesc)
			if self.route:
				self.dstaddr = self.route[3]
				self.dstmode = self.route[4]
				self.state = STATE_C_SYN1
				self.timeout_reset()
				self.log('route ok')
		elif state == STATE_C_SYN1:			# ���ڷ��� syn1
			if self.timeout_check():
				self.host._send_syn1(self.duid, self.dkey, self.sport, \
					self.conv, self.route[1], self.route[2], \
					self.route[3], self.route[4])
		elif state == STATE_C_SYN2:			# ���ڷ��� syn2
			if self.timeout_check():
				self.send(CMD_SYN2, '')
				self.log('send syn2')
		elif state == STATE_READY:
			self._try_ready()
		return 0
	
	# ���׼��״̬��Ϊ���²�Э�����ӣ��������Ӻú�����ready
	def _try_ready (self):
		if self.current >= self.time_mini:
			self._do_establish()
		return 0
	
	# ����״̬
	def _try_working (self):
		if self.current >= self.time_plus:
			self.time_plus = self.current + 1.0
			if self.current >= self.time_alive + TIME_KEEPALIVE:
				self.send(CMD_ALIVE, '%s'%self.current)
			if self.current >= self.time_alive + TIME_KEEPALIVE + 15.0:
				self.log('_try_working: keepalive out of time')
				self._do_disconnect()
		self.protocol.update(self.current)
		while True:
			data = self.protocol.recv()
			if data == None:
				break
			if len(data) >= 2:
				channel = struct.unpack('!H', data[:2])[0]
				self.recvque.append((channel, data[2:]))
		return 0
	
	# ��������
	def _recv_data (self, data):
		if data[:4] == 'CNET':
			self.protocol.input(data)
		elif data[:4] == 'CUNR':
			if len(data) >= 6:
				channel, seq = struct.unpack('!HL', data[4:10])
				#print 'recv unreliable', channel, seq, self.rcv_seq
				if seq >= self.rcv_seq or channel >= 8:
					if channel < 8:
						self.rcv_seq = seq + 1
					self.recvque.append((channel, data[10:]))
		return 0
	
	# ��������
	def senddat (self, channel, data):
		if channel >= 8:
			return -1
		if (channel & 1) == 0:			# �ɿ�����
			text = struct.pack('!H', channel) + data
			self.protocol.send(text)
		else:
			#print 'send unreliable', channel, self.snd_seq
			text = 'CUNR' + struct.pack('!HL', channel, self.snd_seq)
			self.snd_seq += 1
			self.send(CMD_DATA, text + data)
		return 0
	
	# ��������
	def recvdat (self):
		if len(self.recvque) == 0:
			return -1, None
		channel, data = self.recvque.popleft()
		return channel, data

	# ��ʼ�����������ӷ��յ�SYN1ʱ����conn�������øú���
	def _recv_syn1 (self, dport, addr1, mode1, addr2, mode2):
		if self.state != STATE_L_SYN1:
			cnetcom.plog('state error1')
			return -1
		self.dport = dport
		self.head.dport = self.dport
		self.route = (0.2, addr1, mode1, addr2, mode2)
		self.dstaddr = self.route[1]
		self.dstmode = self.route[2]
		self.state = STATE_L_SYN2
		return 0
	
	# ���ӷ��أ���ò�����Զ�̵Ķ˿ڱ��
	def _recv_sack1 (self, port):
		if self.state != STATE_C_SYN1:
			cnetcom.plog('state error2')
			return -1
		self.dport = port
		self.head.dport = port
		self.state = STATE_C_SYN2
		self.timeout_reset()
		return 0

	# ����״̬�µ��������룺syn1, sack1��hostnetά��
	def _input_connecting (self, head, data):
		cmd = head.cmd
		if cmd == CMD_SYN2:					# �����ӷ����յ� syn2
			if self.state == STATE_L_SYN2:
				self._do_getready()			# ����׼���������Ӻ���
			self.send(CMD_SACK2, '')
		elif cmd == CMD_SACK2:				# ���ӷ����յ� syn_ack2
			if self.state == STATE_C_SYN2:
				self._do_getready()			# ����׼���������Ӻ���
		elif cmd == CMD_NOPORT:				# ˫�����յ��˿ڴ���
			self._do_disconnect()
		elif cmd == CMD_NOCONV:				# ˫�����յ��Ự��Ŵ���
			self._do_disconnect()
		elif cmd == CMD_DENY:				# ˫�����ܾ�����
			self._do_disconnect()
		return 0

	# ��������
	def input (self, head, data):
		cmd = head.cmd
		if self.establish == 0:
			self._input_connecting(head, data)
		elif self.establish == 1:
			if cmd == CMD_DATA:
				self._recv_data(data)
			elif cmd == CMD_ACK:
				pass
			elif cmd == CMD_SYN2:
				self.send(CMD_SACK2, '')
			elif cmd == CMD_ALIVE:
				self.send(CMD_ALACK, data)
			elif cmd == CMD_ALACK:
				self.time_rtt = self.current - float(data)
				if self.time_rtt < 0: self.time_rtt = 0
				self.time_alive = self.current
		return 0

	# ����״̬������׼��
	def _do_getready (self):
		self.state = STATE_READY
		self.time_mini = self.current + 1.0
		self.log('_do_getready')

	# ����״̬���Ѿ�����
	def _do_establish (self):
		self.establish = 1
		self.state = STATE_CONNECTED
		self.time_alive = self.current
		self.host._port_establish(self.sport)
		route = self.route
		self.log('route1: %s %d'%(cnetudp.ep2text(route[1]), route[2]))
		self.log('route2: %s %d'%(cnetudp.ep2text(route[3]), route[4]))
		self.log('_do_establish')
	
	# ����״̬���Ͽ�����
	def _do_disconnect (self):
		self.establish = -1
		self.state = STATE_CLOSED
	
	# ����״̬����������
	def update (self, current):
		self.current = current
		if self.establish == 0:
			self._try_connecting()
		elif self.establish == 1:
			self._try_working()


#----------------------------------------------------------------------
# hostnet event - �ⲿЭ��
#----------------------------------------------------------------------
EVT_ESTABLISH		= 0x1000	# event, port, 0
EVT_CLOSED			= 0x1001	# event, port, 0
EVT_DATA			= 0x1002	# event, port, channel

RECV_BLOCKING		= -1		# ���շ��أ�����
RECV_BAD			= -2		# ���շ��أ�����˿�


'''
event, port, channel, data
'''

#----------------------------------------------------------------------
# hostnet - �ն�������
#----------------------------------------------------------------------
class hostnet(cnetcom.hostbase):
	
	def __init__ (self):
		super (hostnet, self).__init__ ()
		self.ports = {}
		self.listen = {}
		self.accepted = []
		self.events = collections.deque()
		self.canlog = 0
	
	# �����ӿڣ���ʼ������
	def init (self, uid, passwd, port = 0, server = None):
		self.quit()
		super (hostnet, self).init(uid, passwd, port, server)
		self.log('[CNET] init(%d, %d, %d)'%(uid, passwd, port))

	# �����ӿڣ��˳�����
	def quit (self):
		super (hostnet, self).quit()
		self.ports = {}
		self.listen = {}
		self.accepted = []
		self.events.clear()
	
	# �����ӿڣ����ӣ����ض˿ڱ��
	def connect (self, uid, passwd, linkdesc):
		endpoint = cnetudp.endpoint()
		try:
			endpoint.unmarshal(linkdesc)
		except:
			self.log('connect: error linkdesc')
			return -1
		self.log('[CNET] connect(%d, %d)'%(uid, passwd))
		if endpoint.nat == None and len(endpoint.local) == 0:
			self.log('connect: empty linkdesc')
			return -2
		conv = self._gen_conv()
		port = self._port_open(TYPE_CONNECTOR, uid, passwd, conv, linkdesc)
		return port

	# �����ӿڣ��ر��ض��˿ڱ�־������
	def close (self, port, reason = ''):
		self.log('[CNET] close(%d)'%port)
		if not port in self.ports:
			return -1
		self._port_close(port, reason)
		return 0
	
	# �����ӿڣ���������
	def accept (self):
		port, uid, passwd, linkdesc = -1, -1, -1, ''
		if len(self.accepted) != 0:
			port, uid, passwd, linkdesc = self.accepted.pop()
			self.log('[CNET] accept: %d, %d, %d'%(port, uid, passwd))
		return port, uid, passwd, linkdesc

	# �����ӿڣ��������ݵ��ض��˿ڵ��ض�ͨ��
	def send (self, port, channel, data):
		if not port in self.ports:
			return -1
		conn = self.ports[port]
		if conn.establish != 1:
			return -2
		conn.senddat(channel, data)
		return 0

	# �����ӿڣ�������Ϣ
	def recv (self, port):
		if not port in self.ports:
			return RECV_BAD, ''
		conn = self.ports[port]
		channel, data = conn.recvdat()
		if channel < 0:
			return RECV_BLOCKING, ''
		return channel, data
	
	# �����ӿڣ����״̬
	def status (self, port):
		if not port in self.ports:
			return RECV_BAD
		conn = self.ports[port]
		if not conn.isalive():
			return RECV_BAD
		if conn.establish == 1:
			return 1
		return 0
	
	# �����ӿڣ�����·��
	def getroute (self, port):
		if not port in self.ports:
			return None
		conn = self.ports[port]
		return conn.route
	
	# �����ӿڣ�ȡ������ʱ�� RTT
	def getrtt (self, port):
		if not port in self.ports:
			return -1
		conn = self.ports[port]
		return conn.time_rtt

	# �����Ϣ����Ϣ����
	def _push (self, event, wparam, lparam, data):
		#self.events.append((event, wparam, lparam, data))
		return 0

	# ����Ƿ��������
	def deny (self, srcuid, srckey):
		return 0
	
	# �򿪶˿�
	def _port_open (self, mode, duid, dkey, conv, linkdesc):
		while 1:
			port = self._gen_port()
			if not port in self.ports:
				break
		conn = connection(mode, self, port, duid, dkey, conv, linkdesc)
		self.ports[port] = conn
		self.log('port_open', port)
		return port

	# �رն˿�
	def _port_close (self, port, reason = ''):
		if not port in self.ports:
			return -1
		conn = self.ports[port]
		ident = conn.duid, conn.dkey, conn.dport
		if (conn.type == TYPE_LISTENER) and (ident in self.listen):
			del self.listen[ident]
		if conn.establish > 0:
			self._push(EVT_CLOSED, port, 0, '')
		conn.close()
		conn = None
		del self.ports[port]
		self.log('port_close', port, reason)
		return 0
	
	# �˿ڽ�����
	def _port_establish (self, port):
		if not port in self.ports:
			return -1
		conn = self.ports[port]
		ident = conn.duid, conn.dkey, conn.dport
		if (conn.type == TYPE_LISTENER) and (ident in self.listen):
			del self.listen[ident]
		self._push(EVT_ESTABLISH, port, 0, '')
		if conn.type == TYPE_LISTENER:
			self.accepted.append((port, conn.duid, conn.dkey, conn.linkdesc))
		self.log('port_estab', port)
		return 0
	
	# д��־
	def log (self, *args):
		if not self.canlog:
			return -1
		cnetcom.plog('[%d]'%(self.uid), *args)
		return 0

	# ���� syn1��Ϣ
	def _send_syn1(self, uid, key, sport, conv, addr1, mode1, addr2, mode2):
		head = cnetcom.msghead(self.uid, self.key, uid, key, sport, 0, \
			CMD_SYN1, conv)
		text = '%s,%d,%s,%d'%(cnetudp.ep2text(addr1), mode1, \
			cnetudp.ep2text(addr2), mode2)
		self.sendudp(head, text, addr2, mode2)
		self.log('syn sport', sport)
		return 0

	# �յ� syn1��Ϣ
	def _recv_syn1(self, head, data, remote, forward):
		deny_it = self.deny(head.suid, head.skey)
		if deny_it:
			newhead = cnetcom.msghead(self.uid, self.key, head.suid, \
				head.skey, 0, head.sport, CMD_DENY)
			self.sendudp(newhead, '', remote, forward)
			return -1
		record = data.split(',')
		if len(record) != 4:
			return -2
		try:
			addr1 = cnetudp.text2ep(record[0])
			mode1 = int(record[1])
			addr2 = cnetudp.text2ep(record[2])
			mode2 = int(record[3])
		except:
			cnetcom.plog('error syn1')
			return -3
		ident = head.suid, head.skey, head.sport
		conn = None
		if ident in self.listen:
			port = self.listen[ident]
			if not port in self.ports:
				del self.listen[ident]
			else:
				conn = self.ports[port]
		if not conn:
			sport = self._port_open(TYPE_LISTENER, head.suid, head.skey, \
				head.conv, '')
			conn = self.ports[sport]
			conn._recv_syn1(head.sport, addr1, mode1, \
				addr2, mode2)
			self.ports[sport] = conn
			self.listen[ident] = conn.sport
		text = '%d'%conn.sport
		conn.send(CMD_SACK1, text)	
		self.log('recv_syn1 from uid=%d key=%d'%(head.suid, head.skey))
		return 0

	# �յ� sack1 ��Ϣ
	def _recv_sack1(self, head, data, remote, forward):
		try:
			port = int(data)
		except:
			cnetcom.plog('error sack1')
			return -1
		sport = head.dport
		dport = head.sport
		if not sport in self.ports:
			cnetcom.plog('no such port %d'%sport)
			msghead = cnetcom.msghead(head.duid, head.dkey, \
				head.suid, head.skey, CMD_NOPORT, head.conv)
			self.sendudp(msghead, '', remote, forward)
			return -2
		conn = self.ports[sport]
		if conn.conv != head.conv:
			cnetcom.plog('conv error %d'%sport)
			msghead = cnetcom.msghead(head.duid, head.dkey, \
				head.suid, head.skey, CMD_NOCONV, head.conv)
			self.sendudp(msghead, '', remote, forward)
			return -3
		conn._recv_sack1(port)
		return 0

	# �յ� syn2��Ϣ
	def _recv_syn2(self, head, data, remote, forward):
		return 0
	
	# �յ� sack2��Ϣ
	def _recv_sack2(self, head, data, remote, forward):
		return 0

	# ת����Ϣ����������
	def _port_dispatch (self, head, data, remote, forward):
		port = head.dport
		conn = None
		if not port in self.ports:
			msghead = cnetcom.msghead(self.uid, self.key, \
				head.suid, head.skey, CMD_NOPORT, head.conv)
			self.sendudp(msghead, '', remote, forward)
			return -1
		conn = self.ports[port]
		if conn.conv != head.conv:
			self.log('dispatch conv error %d cmd=%s'%(port, \
				cnetcom.cmdname(head.cmd)))
			msghead = cnetcom.msghead(self.uid, self.key, \
				head.suid, head.skey, CMD_NOCONV, head.conv)
			self.sendudp(msghead, '', remote, forward)
		conn.input(head, data)
		return 0
	
	# �˿ڸ���
	def _port_update (self):
		for port, conn in self.ports.items():
			conn.update(self.current)
			if len(conn) >= conn.limit:		# ��Ϣ������
				self.log('buffer limit reached')
				conn._do_disconnect()
			if not conn.isalive():			# �Ƿ��Ѿ��Ͽ�������
				self.log('not isalive')
				self._port_close(conn.sport, 'not alive')
		return 0

	# ������Ϣ
	def _process (self, head, data, remote, forward):
		cmd = head.cmd
		if cmd == CMD_SYN1:
			self._recv_syn1(head, data, remote, forward)
		elif cmd == CMD_SACK1:
			self._recv_sack1(head, data, remote, forward)
		elif (cmd >= CMD_SYN2) and (cmd <= CMD_FACK2):
			self._port_dispatch(head, data, remote, forward)
		return 0

	# ����
	def update (self):
		super (hostnet, self).update()
		self._port_update()



#----------------------------------------------------------------------
# hostwan
#----------------------------------------------------------------------
class hostwan(object):
	
	def __init__ (self):
		self.host = hostnet()
		self.current = time.time()
		self.uid = -1
		self.key = -1
	
	# �����ӿڣ���ʼ������
	def init (self, uid, passwd, portudp = 0, server = None):
		self.host.init(uid, passwd, portudp, server)
		self.uid = uid
		self.key = passwd
	
	# �����ӿڣ��˳�����
	def quit (self):
		self.host.quit()
	
	# �����ӿڣ��Ƿ��¼stun������
	def login (self):
		return self.host.network.state
	
	# �����ӿڣ�ȡ�ñ��ص�ַ����
	def localhost (self):
		return self.host.localhost()
	
	# �����ӿڣ�ȡ��ȫ�ֵ�ַ����
	def linkdesc (self):
		return self.host.linkdesc()
	
	# д��־
	def log (self, *argv):
		return self.host.log(*argv)
	
	# �����Ƿ����д��־
	def canlog (self, canlog):
		self.host.canlog = canlog
	
	# �����ӿڣ����ӣ����ض˿ڱ��
	def connect (self, uid, passwd, linkdesc):
		return self.host.connect(uid, passwd, linkdesc)

	# �����ӿڣ��ر��ض��˿ڱ�־������
	def close (self, port):
		return self.host.close(port)
	
	# �����ӿڣ���������
	def accept (self):
		port, uid, key, linkdesc = self.host.accept()
		return port, uid, key, linkdesc
	
	# �����ӿڣ��������ݵ��ض��˿ڵ��ض�ͨ��
	def send (self, port, channel, data):
		return self.host.send(port, channel, data)
	
	# �����ӿڣ�������Ϣ
	def recv (self, port):
		channel, data = self.host.recv(port)
		return channel, data
	
	# �����ӿڣ����״̬
	def status (self, port):
		return self.host.status(port)
	
	# �����ӿڣ�ȡ��·��
	def getroute (self, port):
		return self.host.getroute(port)
	
	# �����ӿڣ�ȡ��rtt
	def getrtt (self, port):
		return self.host.getrtt(port)

	# �����ӿڣ�����
	def update (self):
		self.host.update()
		self.current = time.time()


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
				if host.login() == 1:
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
		host1 = hostwan()
		host2 = hostwan()
		host1.init(201, 8, 0, ('218.107.55.250', 2009))
		host2.init(202, 8, 0, ('218.107.55.250', 2009))
		wait(host1, host2)
		linkdesc = host2.localhost()
		host1.connect(202, 8, linkdesc)
		#print linkdesc
		timeslap = time.time()
		while 1:
			host1.update()
			host2.update()
			time.sleep(0.1)
		return 0
	
	def test2():
		host1 = hostwan()
		host2 = hostwan()
		host1.canlog(1)
		host2.canlog(1)
		cnetcom.plog = cnetcom.plog_stdout
		host1.init(201, 8, 0, ('218.107.55.250', 2009))
		host2.init(202, 8, 0, ('218.107.55.250', 2009))
		wait(host1, host2)
		linkdesc = host2.localhost()
		port1 = host1.connect(202, 8, linkdesc)
		while 1:
			host1.update()
			host2.update()
			time.sleep(0.1)
			if host1.status(port1) != 0:
				break
		print 'connected', host1.status(port1)
		port2, uid, key, linkdesc = host2.accept()
		print 'accept', port2, uid, key, linkdesc, host2.status(port2)
		time_slap = time.time() + 1.0
		time_life = time.time() + 10

		index = 0
		while 1:
			time.sleep(0.005)
			host1.update()
			host2.update()
			#print '.'
			current = time.time()
			if current >= time_slap:
				host1.send(port1, 7, 'packet_%d %f'%(index, current))
				#print '[SEND]', index, host1.status(port1)
				time_slap = current + 0.5
				index += 1
			while True:
				channel, data = host2.recv(port2)
				if channel >= 0:
					#print 'r', channel, data
					host2.send(port2, channel, data)
				else:
					break
			while True:
				channel, data = host1.recv(port1)
				if channel >= 0:
					record = data.split(' ')
					timepass = current - float(record[1])
					print '[RECV]', channel, record[0], timepass, host1.getrtt(port1)
				else:
					break
			if current >= time_life:
				#host2.close(port2)
				pass
		return 0

	test2()



