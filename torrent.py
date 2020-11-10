#import torrent_parser as tp
import sys,requests,hashlib,bencodepy,random
import socket
from urllib.parse import urlparse
from struct import *
from _thread import *
from threading import *
import logging
import math
import time
import decoding
import string
import os

#general torrent settings
torrent_par={
	"max_d_speed": 0,
	"max_u_speed": 0,
	"pieces_downloaded": 0,
	"download_location":os.getcwd()+"/",
	"upload_location":""
}

if(len(sys.argv )<2):
	print("Invalid arguments")
	sys.exit(1)
else:
	if(not os.path.isfile(sys.argv[1])):
		raise Exception()
	try:
		for i in range(2,len(sys.argv),2):
			if(sys.argv[i] == '-d'):
				print(int(sys.argv[i+1]))
				torrent_par['max_d_speed'] = int(sys.argv[i+1])
			if(sys.argv[i] == '-l'):
				if(os.path.isdir(sys.argv[i+1])):
					torrent_par["download_location"] = sys.argv[i+1] + "/"	
				else:
					raise Exception() 
	except Exception as e:
		logging.exception(e)
		print("Invalid args")
		sys.exit(1)		

f = open(sys.argv[1] , "rb")
met = bencodepy.decode(f.read())
meta = {}
for key, val in met.items():
	meta[key.decode()] = val	

metadata = decoding.decode_torrent(sys.argv[1])
info_digest = hashlib.sha1(bencodepy.encode(meta['info'])).digest()

#random generated peer id for this client
PEER_ID = ''.join(random.choice(string.digits) for i in range(0))
#port number this client is goinf to listen on for request from other peers
PORT_NO = 6881

par = {
	"info_hash": info_digest,
	"peer_id" : PEER_ID,
	"uploaded" : 0,
	"downloaded" : 0,
	"left":metadata['info']['length'],
	"port":PORT_NO
}

#This list keeps track of all pieces related information
received_pieces = [{"index": i, "done" : False, "downloading" : False, "begin": 0 , "downloading_peer": None, "available": 0, "count": 0 } for i in range(0,len(metadata['info']['pieces']))]

#A sorted list of pieces dpending on availablity of these pieces among the peers
rarest_pieces = []

# Opening torrent file.
try:
	downloading_file = open(torrent_par['download_location']+metadata['info']['name'],"rb+")	
except:
	create = open(torrent_par['download_location']+metadata['info']['name'],"w")
	create.close()
	downloading_file = open(torrent_par['download_location']+metadata['info']['name'],"rb+")

#List of all peers retuened by the tracker
peers = []


t_lock = Lock() # lock for received pieces list
rarest_lock = Lock() # losck for rarest piece list
p_lock = Lock()	#lock for peers list

def http_tracker(url, par):
	global peers
	try:
		response = requests.get(url, params = par, timeout = 10)
		if(response):
			#print(bencodepy.decode(response.content),response)
			tmp,peer_data = {}, bencodepy.decode(response.content)
				
			for key, val in peer_data.items():
				tmp[key.decode()] = val
				
			peer_data = tmp	
			for peer in peer_data['peers']:
				tmp = {}
				for key, val in peer.items():
					tmp[key.decode()] = val		
				del tmp['peer id']
				tmp['ip'] = tmp['ip'].decode()
				p_lock.acquire()
				peers.append(tmp)
				p_lock.release()		
	except Exception as e:
		#print("Error reaching http tracker", url)
		#print(e)
		return None	
	

def udp_tracker(domain, port, par):
	global peers
	'''Connection Request and Response'''
	protocol_id = 0x41727101980
	action  = 0  #connection
	transaction_id = random.randrange(0, 2147483647)
	
	data = pack('!qii',protocol_id,action,transaction_id)
	#print(data)
	#print(domain,port)
	#print(calcsize('!qii'))
	n = 0
	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	sock.settimeout(10)
	try:
		sock.sendto(data,(domain,int(port)))
	except Exception as e:
		#print("Could not connect to tracker", domain, port)
		#print(str(e))
		return None	
	try:
		data, server = sock.recvfrom(1024)
		#print(unpack('!iiq',data))
		action,transaction_id,connection_id = unpack('!iiq',data)	
	except:
		#print("No response")
		return None

	''' IPV4 Announce Request and Response'''
	action  = 1 #announce 
	#connection_id, transaction_id is same
	event, ip_address, key, num_want = 0 ,0 , random.randrange(0, 2147483647),-1 
	data = pack('!qii20s20sqqqiiiih', connection_id,action,transaction_id,par['info_hash'],par['peer_id'].encode(),par['downloaded'],par['left'],par['uploaded'],event,ip_address,key,num_want,par['port'])
	#print(calcsize('!qii20s20sqqqiiiih'))
	try:
		sock.sendto(data,(domain,int(port)))
	except Exception as e:
		#print("Could not connect to tracker",domain,port)
		#print(str(e))
		return None
	try:
		data, server = sock.recvfrom(1024)
		#print("length", len(data))
		if(len(data) >= 20):
			action, transaction_id_tmp, inteval, leechers, seeders = unpack('!iiiii',data[:20])	
			#print(unpack('!iiiii',data[:20]))
			n = int((len(data)-20) / 6)
			#print(unpack("!iiiii"+(n*'IH'),data))
			res = unpack("!"+n*'BBBBH',data[20:])
			#peers = []
			p_lock.acquire()
			for x in range(0,len(res),5):
				i1,i2,i3,i4,port = res[x:x+5]
				ip = str(i1)+"."+str(i2)+"."+str(i3)+"."+str(i4)
				peers.append({'ip':ip, 'port':port})
			p_lock.release()	
			#return peers	
	except Exception as e:
		#print("No response for announce", domain, port)
		#print(str(e))
		return None		
	

def get_all_peers(metadata, par):
	url_p = urlparse(metadata['announce'])
	global peers
	http_threads = []
	udp_threads = []
	if(url_p.scheme == 'http' or url_p.scheme == 'https'):
		#http_tracker(metadata['announce'],par)
		http_threads.append(Thread(target = http_tracker,args = (metadata['announce'],par)))
		

	elif(url_p.scheme == 'udp'):
		domain, port = url_p.netloc.split(":")
		#udp_tracker(domain,port,par)
		udp_threads.append(Thread(target = udp_tracker, args = (domain,port,par)))

	for tracker in metadata['announce-list']:
		url_p = urlparse(tracker[0])
		if(url_p.scheme == 'udp'):
			domain, port = url_p.netloc.split(":")
			#udp_tracker(domain,port,par)
			udp_threads.append(Thread(target = udp_tracker, args = (domain,port,par)))
			
		elif(url_p.scheme == 'https' or url_p.scheme == 'http'):
			#http_tracker(tracker[0], par)
			http_threads.append(Thread(target = http_tracker,args = (tracker[0], par)))

	for h in http_threads:
		h.start()
	for u in udp_threads:
		u.start()
	for h in http_threads:
		h.join()
	for u in udp_threads:
		u.join()			
	tmp = []
	for peer in peers:
		if peer not in tmp:
			tmp.append(peer)
	peers = tmp	

def peer_communication(ip, port, par, peer_index, torrent_par):
	global rarest_pieces
	#print(ip, port)
	peer_id = b''
	if type(ip) is bytes:
		ip = ip.decode()
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	sock.settimeout(30)
	try:
		sock.connect((ip,port))
		#print("connected to ..",ip,port)
		
	except Exception as e:
		#print("Could not connect to peer...")
		#print(e)
		return

	try:
		'''state meanings ;
			0 = No handshake yet
			1 = Handshake done
			2 = Got bitfield
			3 = unchoked
		'''
		state = 0
		alive = 1
		bitfield = b''
		index = 0
		while(alive):
			#print("state=",state)

			if(state == 0):
				ch = chr(19)			
				msg = pack('!c19sii20s20s',ch.encode(),b'BitTorrent protocol',0,0,par['info_hash'],par['peer_id'].encode())
				sock.send(msg)

			if(state == 2):
				#send interested message
				rarest_lock.acquire()
				# increment the count of all available pieces
				p =1
				for i in range(0,len(bitfield)):
					x = unpack("B",bitfield[i:i+1])[0]
					q = 1
					for j in range(0,8):
						if(x & 1<<j):
							received_pieces[p*8-q]["count"] = received_pieces[p*8-q]["count"] + 1
						q = q+1	
					p=p+1
				rarest_pieces = sorted(received_pieces, key = lambda k: k['count'])
				#print(rarest_pieces)
				rarest_lock.release()	
				msg = pack('!IB',1,2)
				try:
					#print("Sending interested...")
					sock.send(msg)
				except Exception as e:
					#print("Error while sending interested message")
					#print(e)
					pass

			if(state == 3):
				
				flag = True

				for k in range(0, len(rarest_pieces)):
					#p =1
					p = math.floor(rarest_pieces[k]['index']/8) + 1
					byte = math.floor(rarest_pieces[k]['index']/8)
					#for i in range(0,len(bitfield)):
					x = unpack("B",bitfield[byte:byte+1])[0]
					q = 1					
					for j in range(0,8):
						bit_index = p*8-q
						if(x & 1<<j):
							if(bit_index == rarest_pieces[k]['index']):
								if(bit_index == len(metadata['info']['pieces'])-1):
									piece_length = metadata['info']['length'] - (bit_index)*metadata["info"]['piece length']
								else:
									piece_length = metadata["info"]['piece length']

								if received_pieces[bit_index]["done"] == False and (received_pieces[bit_index]["downloading"] == False  or received_pieces[bit_index]["downloading_peer"] == peer_id ):
									
									received_pieces[bit_index]["downloading_peer"] = peer_id

									remaining = piece_length - received_pieces[bit_index]["begin"]
									index, begin = bit_index,received_pieces[bit_index]["begin"]
									if(remaining > 2**14):
										piece_len = 2**14
									else:
										piece_len = remaining

									t_lock.acquire()			
									received_pieces[bit_index]["downloading"] = True
									t_lock.release()

									flag = False
									break		
						else:
							#print(bit_index, end="")
							pass
						q = q+1	
					#p=p+1
					if(flag == False):
						break
				if(flag):
					alive = 0
					break
				
				# send piece request
					
				msg = pack('!IBIII',13,6,index,begin,piece_len)		
				sock.send(msg)
					
			t1 = time.time()
			res = sock.recv(2**20)
			t2 = time.time()
			if(torrent_par['max_d_speed'] != 0):
				actual_time = t2-t1
				required_time = (len(res)/1000)/torrent_par['max_d_speed']
				if(required_time > actual_time):
					time.sleep(required_time - actual_time)
					t2 = time.time()	

			if(peers[peer_index]['d_speed'] == 0):
				peers[peer_index]['d_speed'] = ((len(res) * 0.001)/(t2 - t1))  
			else: 
				peers[peer_index]['d_speed'] = round((peers[peer_index]['d_speed'] + ((len(res) * 0.001)/(t2 - t1)))/2,3)
			
			#print(len(res))
			
			if(len(res) == 0):
				raise Exception("Connection lost ...")
				state = 0
				continue
				#raise Exception("Connection error")
			
			if(state == 0):
				if len(res) < 68:
					break
				else:
					handshake = unpack('!s19sii20s20s',res[:68])
					#print(handshake[5])
					peer_id = handshake[5]
					state = 1
					res = res[68:]
							
			packet_len = len(res)

			while(packet_len > 0):			
				length = unpack("!I",res[:4])[0]
				if(length == 0):
					break
				typ = unpack("!B",res[4:5])[0]
				res = res[5:]

				#print(length,typ)

				#type 0 choke
				if(typ == 0):
					alive = 0
					break
				
				#type 5 bitfield
				if(typ == 5):
					if(len(res) >= length-1):
						bitfield = unpack(str(length-1)+'s',res[:length-1])[0]
						res = res[length:]
						print(bitfield)
						state = 2
						break
					else:	
						bitfield = unpack(str(len(res))+'s', res)[0]
					#print(bitfield)
					
					bit_rem = length-1 - len(res)
					
					res = res[len(res):]

					while(bit_rem > 0):
						t1 = time.time()
						bit_c = sock.recv(4096)
						t2 = time.time()
						if(torrent_par['max_d_speed'] != 0):
							actual_time = t2-t1
							required_time = (len(bit_c)/1000)/torrent_par['max_d_speed']
							if(required_time > actual_time):
								time.sleep(required_time - actual_time)
								t2 = time.time()

						if(peers[peer_index]['d_speed'] == 0):
							peers[peer_index]['d_speed'] = ((len(bit_c) * 0.001)/(t2 - t1))  
						else: 
							peers[peer_index]['d_speed'] = round((peers[peer_index]['d_speed'] + ((len(bit_c) * 0.001)/(t2 - t1)))/2,3)
						
						if(len(bit_c) > bit_rem):
							bitfield = bitfield + unpack(str(bit_rem) + 's', bit_c[:bit_rem])[0]
							res = bit_c[bit_rem:]
							break
						else:
							bitfield = bitfield + unpack(str(len(bit_c))+'s', bit_c)[0]
							bit_rem = bit_rem - len(bit_c)	
					#print(bitfield)	
					#print(len(bitfield))
						
					if(math.ceil(math.log(len(bitfield)*8,2)) == math.ceil(math.log(len(metadata['info']['pieces']),2))):
						state = 2		
						
				# type 1 = unchoke
				if(typ == 1):
					state = 3
				
				#type 4 = have
				if(typ == 4):
					res = res[4:]

				#type 7 = piece block receive	
				if(typ == 7):
					rem_piece_len = length -9
					index, begin = unpack('!II',res[:8])

					#print("receiving block ",index,"begin at",begin,"of length",length-9)

					res = res[8:]

					if(len(res) > rem_piece_len):
						block = unpack(str(rem_piece_len)+"s",res[:rem_piece_len])[0]
						rem_piece_len = rem_piece_len - len(res)
						res = res[rem_piece_len:]
						break;
					else:
						block = unpack(str(len(res))+'s',res)[0]
						rem_piece_len = rem_piece_len - len(res)
						res = res[len(res):]	

					while(rem_piece_len > 0):
						t1 = time.time()
						block_c = sock.recv(2**16)
						t2 = time.time()
						if(torrent_par['max_d_speed'] != 0):
							actual_time = t2-t1
							required_time = (len(block_c)/1000)/torrent_par['max_d_speed']
							if(required_time > actual_time):
								time.sleep(required_time - actual_time)
								t2 = time.time()

						if(peers[peer_index]['d_speed'] == 0):
							peers[peer_index]['d_speed'] = ((len(block_c) * 0.001)/(t2 - t1))  
						else: 
							peers[peer_index]['d_speed'] = round((peers[peer_index]['d_speed'] + ((len(block_c) * 0.001)/(t2 - t1)))/2,3)

						if(len(block_c) >= rem_piece_len):	
							block = block + unpack(str(rem_piece_len)+'s',block_c[:rem_piece_len])[0]
							rem_piece_len = rem_piece_len - len(block_c)
							#res = block_c[rem_piece_len:]
						else:
							block = block + unpack(str(len(block_c))+'s', block_c)[0]
							rem_piece_len = rem_piece_len - len(block_c)
					
					write_piece(index,begin,block)
					#print("Received block length", len(block))

					received_pieces[index]['begin'] = received_pieces[index]['begin'] + len(block) 
					
					if(index == (len(metadata['info']['pieces'])-1)):
						if(received_pieces[index]['begin'] == (metadata['info']['length'] - (index * metadata['info']['piece length']))):
							
							block_hash = hashlib.sha1(read_piece(index)).hexdigest()
							#print(block_hash)

							#print(metadata['info']['pieces'][index])
							if(block_hash == metadata['info']['pieces'][index]):
								received_pieces[index]["done"] = True
								received_pieces[index]["downloading"] = False
								torrent_par['pieces_downloaded'] += 1
								break
							else:
								received_pieces[index]["begin"] = 0
								received_pieces[index]["downloading"] = False
									
								break
					else:			
						if(received_pieces[index]['begin'] == metadata['info']['piece length']):
							
							block_hash = hashlib.sha1(read_piece(index)).hexdigest()
							#print(block_hash)

							#print(metadata['info']['pieces'][index])
							if(block_hash == metadata['info']['pieces'][index]):
								received_pieces[index]["done"] = True
								received_pieces[index]["downloading"] = False	
								torrent_par['pieces_downloaded'] += 1
								break
							else:
								received_pieces[index]["begin"] = 0
								received_pieces[index]["downloading"] = False	
								break
				packet_len = len(res)
					
	except Exception as e:
		received_pieces[index]["downloading"] = False
		#logging.exception(e)				

def write_piece(index,begin,block):
	downloading_file.seek((index * metadata['info']['piece length'])+begin,0)
	downloading_file.write(block)

def read_piece(index):
	downloading_file.seek((index * metadata['info']['piece length']),0)
	
	if(index == len(metadata['info']['pieces'])-1):
		piece = downloading_file.read(metadata['info']['length'] - (index * metadata['info']['piece length']))
	else:
		piece = downloading_file.read( metadata['info']['piece length'])
	return piece	

def print_progress():
	global torrent_par
	progress = 0
	while(progress != 100):
		progress = round(torrent_par['pieces_downloaded']/len(metadata['info']['pieces'])*100,2)
		print("Downloaded", progress,"%", end = "\r")
		time.sleep(0.2)

#print(len(metadata['info']['pieces']))

while(torrent_par['pieces_downloaded'] != len(metadata['info']['pieces'])):
	
	print("Getting peer information from trackers...")
	get_all_peers(metadata,par)						
	print("Got",len(peers),"peers... :-)")

	peer_threads = []

	for peer in peers:
		peer['d_speed'] = 0

	for peer in peers:
			peer_threads.append(Thread(target = peer_communication, args = (peer['ip'],peer['port'],par, peers.index(peer),torrent_par)))
			#peer_communication(peer['ip'],peer['port'],par)
	print("Started downloading...")
	Thread(target = print_progress).start()	
	for peer_t in peer_threads:
		peer_t.start()

	for peer_t in peer_threads:
		peer_t.join()

print("----------------------------------TOP 4 PEERS-------------------------------------")
for x in sorted(peers, key = lambda k: k['d_speed'], reverse = True)[:4]:
	print(x['ip'],"Download speed is",x['d_speed'],"Kbps")

print("----------------------------------RAREST PIECES------------------------------------")
for x in rarest_pieces:
	print(x['index'],end = " ")

print()	
			