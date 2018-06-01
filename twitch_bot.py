#!/usr/bin/python
# -*- coding: utf-8 -*-

import requests
import datetime
import socket
import logging
import random
import sys
import time
import threading


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(thread)d - %(message)s')
fh = logging.FileHandler('debug.log', encoding='utf-8')
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)
locker=threading.Lock()

url = 'https://api.twitch.tv/helix'
client_id = ''     # https://dev.twitch.tv/dashboard/apps/create
login = ''                               # https://twitchapps.com
oauth = ''         # https://twitchapps.com/tmi/
channel=''                                 # https://www.twitch.tv/directory/all


class TwHelix(object):

    def __init__(self,  client_id, channel):
        self.client_id = client_id
        self.api_url = 'https://api.twitch.tv/helix'
        self.channel = channel
        self.channel_id = self.get_channel_id(channel)


    def get_channel_id(self, channel):
        r = requests.get(url=self.api_url+'/users',
                         params={'login': channel},
                         headers= {'Client-ID': self.client_id}).json()
        return None if not r['data'] else r['data'][0]['id']

    @classmethod
    def time_delta(self, jt):
        tf = "%Y-%m-%dT%H:%M:%SZ"
        td = datetime.datetime.utcnow()-datetime.datetime.strptime(jt, tf)
        tsplit = {'y': td.days//365, 'd': td.days % 365, 'h': (td.seconds//3600) % 24,
                  'min': (td.seconds//60) % 60, 'sec': td.seconds % 60}
        return ' '.join([str(v)+k for k, v in tsplit.items() if v])

    def get_cur_game(self):
        r=requests.get(url=self.api_url+'/streams',
                       params={'user_id': self.channel_id},
                       headers= {'Client-ID': self.client_id}).json()
        if not r['data']:
            return 'stream offline'
        r=requests.get(url=self.api_url+'/games',
                       params={'id':r['data'][0]['game_id']},
                       headers= {'Client-ID': self.client_id}).json()
        return r['data'][0]['name']

    def get_stm_uptime(self):
        r=requests.get(url=self.api_url+'/streams',
                       params={'user_id': self.channel_id},
                       headers= {'Client-ID': self.client_id}).json()
        return None if not r['data'] else self.time_delta(r['data'][0]['started_at'])

    def follow_time_byid(self, from_id, to_id=''):
        if not to_id:
            to_id=self.channel_id
        r=requests.get(url=self.api_url+'/users/follows',
                       params={'from_id':from_id, 'to_id':to_id},
                       headers= {'Client-ID': self.client_id}).json()
        return None if not r['data'] else self.time_delta(r['data'][0]['followed_at'])

    def strim_info(self):
        r = requests.get(url=self.api_url + '/streams',
                     params={'user_id': self.channel_id},
                     headers={'Client-ID': self.client_id}).json()
        return None if not r['data'] else dict(r['data'][0])



class Twitch_irc_bot():

    def __init__(self, login, oauth, helix ):
        self.server = 'irc.chat.twitch.tv'
        self.port = 6667
        self.login = login
        self.token = oauth
        self.channel = helix.channel
        self.socket=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.server, self.port))
        self.helix=helix
        self.cmd_d = {'roll': lambda s, a: 'Your number: {}'.format(random.randint(1, 100)),
                      'game': lambda s, a : 'Current game: {}'.format(self.helix.get_cur_game()),
                      'uptime': lambda s, a: 'Stream online: {}'.format(self.helix.get_stm_uptime()),
                      'followage': lambda s, a: 'You are already followed : {}'.format(
                          self.helix.follow_time_byid(from_id=self.helix.get_channel_id(s))),
                      'commands': lambda s, a: 'Supported commands: ' + ', '.join(['!' + k for k in self.cmd_d]),
                      'history': lambda s,a : 'command not implemented yet D:'
                        }
    def join(self):
        self.socket.send('PASS oauth:{}\r\nNICK {}\r\n'.format(self.token, self.login).encode())
        print(self.socket.recv(2048).decode())
        for cap in ['membership', 'tags', 'commands']:
            self.socket.send('CAP REQ :twitch.tv/{}\r\n'.format(cap).encode())
            print(self.socket.recv(2048).decode())
        self.socket.send('JOIN #{0}\r\n'.format(self.channel).encode())
        print(*(self.socket.recv(2048).decode('utf-8') for _  in [1, 2]), sep='\r\n')

    def commands(self, src, c ):
        print(src, c, sep=' ')
        if c in self.cmd_d:
           self.privmsg(src, self.cmd_d[c](src,c))

    def privmsg(self, name='', msg=''):
        m = 'PRIVMSG #' + self.channel + ' :' + str()
        m = 'PRIVMSG #{} :@{} {}\r\n'.format(self.channel, name, msg)
        self.socket.send(m.encode())

    def read_loop(self):
        while True:
            try:
                raw = self.socket.recv(2048)
                r=raw.decode('utf-8')
                r = r[:r.index('\r\n')].strip().split(' ')
                if r[0] == 'PING':
                    self.socket.send('PONG :tmi.twitch.tv\r\n'.encode())
                    logger.debug('PONG')
                else:
                    msg=dict(zip(['tags', 'source', 'type', 'channel', 'args'],
                                  [i for i in r[:4]] + [' '.join(r[4:])]))
                    msg['source']=msg['source'][1:((len(msg['source']) - 17) // 3)+1]
                    if msg['type']=='PRIVMSG':
                        logger.debug('source: {}, args: {}'.format(msg['source'], msg['args']))
                        if msg['args'][1]=='!':
                            logger.debug('commands {}'.format(msg['args'][1:]))
                            self.commands( msg['source'],msg['args'][2:])
            except UnicodeDecodeError:
                logger.debug('UnicodeDecodeError {}'.format(sys.exc_info()))
            except ValueError:
                pass
            except KeyError:
                pass

    def games_logging(self):
        l = []
        global locker
        game = self.helix.get_cur_game()
        stime = self.helix.get_stm_uptime()
        l.append([game, stime])
        while True:
            with locker:
                time.sleep(30)
                t = self.helix.get_cur_game()
                logger.debug('Текущая игра {}'.format(game))
                if game != t:
                    game = t
                    l.append([game, time.ctime(time.time())])
                    logger.debug(
                        'Игра поменялась на {}, {}'.format(game, ' => '.join([i[0] + ' ' + str(i[1]) for i in l])))


if __name__ == '__main__':
    tw=TwHelix(client_id , channel)
    ircchat=Twitch_irc_bot(login, oauth, tw )
    ircchat.join()
    thd=[]
    chat=threading.Thread(target=ircchat.read_loop)
    thd.append(chat)
    wtlog=threading.Thread(target=ircchat.games_logging )
    thd.append(wtlog)
    for i in thd:
        i.start()
    for i in thd:
        i.join()

