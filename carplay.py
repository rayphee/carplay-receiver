#!/usr/bin/python3

# "Autobox" dongle driver for HTML 'streaming' - test application
# Created by Colin Munro, December 2019
# See README.md for more information

"""Implementation of electric-monk's pycarplay for use with head-units"""
import asyncio
import queue
import decoder
import audiodecoder
import link
import protocol
from threading import Thread
import time
import queue
import os
import struct
import kivy
from kivy.app import App, async_runTouchApp
from kivy.uix.widget import Widget

MT_QUEUE = queue.Queue() # I know, I hate globals too

class TouchLayer(Widget):
    def on_touch_down(self, touch):
        MT_QUEUE.put((touch, 'down'))
        # print(touch.pos)
    def on_touch_move(self, touch):
        MT_QUEUE.put((touch, 'move'))
        # print(touch.pos)
    def on_touch_up(self, touch):
        MT_QUEUE.put((touch, 'up'))
        # print(touch.pos)

class CarPlayReceiver:
    class _Decoder(decoder.Decoder):
        def __init__(self, owner):
            super().__init__()
            self._owner = owner
        def on_key_event(self, event):
            print(f'Got a key event: {event}')
            self._owner.connection.send_key_event(event)
            if event == decoder.KeyEvent.BUTTON_SELECT_DOWN:
                self._owner.connection.send_key_event(decoder.KeyEvent.BUTTON_SELECT_UP)
    class _AudioDecoder(audiodecoder.AudioDecoder):
        def __init__(self, owner):
            super().__init__()
            self._owner = owner
    class _Connection(link.Connection):
        def __init__(self, owner):
            super().__init__()
            self._owner = owner
            self._owner.av_queue = queue.Queue()
            self.put_thread = Thread(target=self._put_thread, args=[self._owner])
            self.put_thread.start()
        def _put_thread(self, owner):
            self._owner = owner
            while True:
                while self._owner.av_queue.qsize():
                    message = self._owner.av_queue.get()                
                    if isinstance(message, protocol.Open):
                        if not self._owner.started:
                            self._owner._connected()
                            self.send_multiple(protocol.opened_info)
                    elif isinstance(message, protocol.VideoData):
                        self._owner.decoder.send(message.data)
                    elif isinstance(message, protocol.AudioData):
                        try:
                            self._owner.audio_decoder.send(message.data)
                        except Exception as e:
                            print(f"exception: {e}")
        def on_message(self, message):

                self._owner.av_queue.put(message);
                
        def on_error(self, error):
            self._owner._disconnect()
    def __init__(self):
        self._disconnect()
        # self.server = self._Server(self)
        self.decoder = self._Decoder(self)
        self.audio_decoder = self._AudioDecoder(self)
        self.heartbeat = Thread(target=self._heartbeat_thread)
        self.heartbeat.start()
    def _connected(self):
        print("Connected!")
        self.started = True
        self.decoder.stop()
        self.audio_decoder.stop()
        self.decoder = self._Decoder(self)
        self.audio_decoder = self._AudioDecoder(self)
    def _disconnect(self):
        if hasattr(self, "connection"):
            if self.connection is None:
                return
            print("Lost USB device")
        self._frame = b''
        self.connection = None
        self.started = False
    def _heartbeat_thread(self):
        while True:
            try:
                self.connection.send_message(protocol.Heartbeat())
            except link.Error:
                self._disconnect()
            except:
                pass
            time.sleep(protocol.Heartbeat.lifecycle)
    def _keylistener_thread(self, caller):
        while True:
            input1 = int(input())
            print(f'you entered {input1}')
            keys = protocol.CarPlay()
            mcVal = struct.pack("<L",input1)
            keys._setdata(mcVal)            
            caller.connection.send_message(keys)
    def _multitouch_thread(self, caller):
        while True:
            try:
                mt_input = []
                while not MT_QUEUE.empty():
                    mt_input.append(MT_QUEUE.get_nowait())
                if mt_input:
                    touches = protocol.MultiTouch()
                    for t in mt_input:
                        print("MT Thread, Touch Input: {}, Position: {}".format(t[1], t[0].pos))
                        touch = protocol.MultiTouch.Touch()
                        action = 0
                        if t[1] == "up":
                            action = 0
                        elif t[1] == "down":
                            action = 1
                        else: # consider "move"
                            action = 2
                        # touch_data = struct.pack("<ffLL", t.pos.x, t.pos.y, action)
                        # touch._setdata(touch_data)
                        touch.x = t[0].pos.x * (1/8000000)
                        touch.y = t[0].pos.y * (1/6000000)
                        touch.action = action
                        touches.touches.append(touch)
                    caller.connection.send_message(touches)
            except queue.Empty:
                pass
        pass
        # while True:
        #     touch_input = multitouch.input()
        #     caller.connection.send_message(touch_input)
    async def run(self):
        self.keylistener = Thread(target=self._keylistener_thread, args=(self,))
        self.multitouch = Thread(target=self._multitouch_thread, args=(self,))
        self.keylistener.start()
        self.multitouch.start()
        while True:
            # First task: look for USB device
            while self.connection is None:
                try:
                    self.connection = self._Connection(self)
                except Exception as e:
                    pass
            print("Found USB device...")
            # Second task: transmit startup info
            try:
                while not self.started:
                    self.connection.send_multiple(protocol.startup_info)
                    time.sleep(1)
            except:
                self._disconnect()
            print("Connection started!")
            # Third task: idle while connected
            while self.started:
                await asyncio.sleep(1)

async def run_touch_layer(touch_layer):
    await async_runTouchApp(touch_layer, async_lib='asyncio')

def build_layers(touch_layer, receiver_layer):
    receiver_task = asyncio.ensure_future(receiver_layer.run())
    return asyncio.gather(run_touch_layer(touch_layer), receiver_task)

if __name__ == "__main__":
    touch_layer = TouchLayer()
    receiver_layer = CarPlayReceiver()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(build_layers(touch_layer, receiver_layer))
    loop.close()
