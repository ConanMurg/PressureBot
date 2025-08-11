# -*- coding: utf-8 -*-
"""
Created on Mon Feb 26 15:33:10 2024

@author: Conan Murgatroyd
"""

import tkinter as tk
from tkinter import ttk
import threading
from threading import Timer, Event
import time
import matplotlib.pyplot as plt
import matplotlib.dates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.backend_bases import key_press_handler
from matplotlib.ticker import ScalarFormatter
import telebot
import os
from dotenv import load_dotenv
from datetime import datetime
from datetime import timedelta
import ctypes
import numpy as np
from picosdk.pl1000 import pl1000 as pl
from picosdk.functions import adc2mVpl1000, assert_pico_ok
import socket
import math
import collections

# def internet(host="8.8.8.8", port=53, timeout=3):
#     """
#     Returns true if internet connection is active, False otherwise.

#     Info:
#     Host: 8.8.8.8 (google-public-dns-a.google.com)
#     OpenPort: 53/tcp
#     Service: domain (DNS/TCP)
#     """
#     try:
#         socket.setdefaulttimeout(timeout)
#         socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
#         return True
#     except socket.error as ex:
#         print(ex)
#         return False


def format_time(offset=0):
    """
    Returns current time in Year-M-D H:M:S format. Offset in seconds. Default of 0.
    """
    t = datetime.now() - timedelta(seconds=offset)
    # print(t)
    if t.microsecond % 1000 >= 500:  # check if there will be rounding up
        t = t + timedelta(milliseconds=1)  # manually round up
    return t.strftime('%Y:%m:%d %H:%M:%S%f')[:-6]


def OpenUnit(chandle, status, channel=16, nr_of_values=10000, us_for_block=100000):
    """
    Opens PicoLog Data Logger 1216.

    Parameters
    ----------
    chandle : c_int16
        Empty ctypes.c_int16().

    status : dictionary
        Empty dictionary to store device status codes.

    channel : int, optional
        Data Logger input channel. Ranges between 1 and 16 (default).

    nr_of_values : int, optional
        Specifies how many readings to take.

    us_for_block : int, optional
        Specifies how long to stream for.

    Returns
    -------
    None

    """
    # open PicoLog 1000 device
    status["openUnit"] = pl.pl1000OpenUnit(ctypes.byref(chandle))
    assert_pico_ok(status["openUnit"])

    # set sampling interval
    usForBlock = ctypes.c_uint32(us_for_block)  # 1 Second (5e5 microseconds)
    noOfValues = ctypes.c_uint32(nr_of_values)  # 5e5 measurements
    channels = ctypes.c_int16(16)

    status["setInterval"] = pl.pl1000SetInterval(
        chandle, ctypes.byref(usForBlock), noOfValues, ctypes.byref(channels), 1)
    assert_pico_ok(status["setInterval"])

    return [chandle, status, noOfValues]


def AverageReading(chandle, status, noOfValues):
    """
    STREAM DATA
    """
    # Start streaming
    mode = pl.PL1000_BLOCK_METHOD["BM_STREAM"]
    status["run"] = pl.pl1000Run(chandle, noOfValues.value, mode)
    assert_pico_ok(status["run"])

    # Wait for device to finish collecting data
    time.sleep(0.5)  # time must be longer than usForBlock

    # Get values
    values = (ctypes.c_uint16 * noOfValues.value)()
    oveflow = ctypes.c_uint16()
    status["getValues"] = pl.pl1000GetValues(chandle, ctypes.byref(
        values), ctypes.byref(noOfValues), ctypes.byref(oveflow), None)
    assert_pico_ok(status["getValues"])

    # Convert adc values to mV
    maxADC = ctypes.c_uint16(4095)
    inputRange = 2500
    mVValues = adc2mVpl1000(values, inputRange, maxADC)

    # Divide by 1000 to return answer in Volts not mV.
    return [chandle, status, np.mean(mVValues) / 1000]


def CloseUnit(chandle, status):
    """
    CLOSE DEVICE
    """
    # close PicoLog 1000 device
    status["closeUnit"] = pl.pl1000CloseUnit(chandle)
    assert_pico_ok(status["closeUnit"])


def volts2mbar(voltage):
    """
    Voltage - milivolts

    Returns
    -------
    Pressure (mbar)
    """
    if not isinstance(voltage, float):
        return

    # Maximum voltage of 8.6, scaled by 4.16 gives max of ~ 2.066
    voltage = min(voltage, 2.066414)

    # Scale voltage up by 4.246 because of potential divider
    voltage = voltage * 4.16

    # Before converting voltage to pressure.
    pressure = 10**(1.667*voltage-11.33)

    # return "{:.2e}".format(pressure)
    return pressure


def decay_generator(start, end, num_points):
    decay_factor = math.exp(math.log(end / start) / (num_points - 1))
    values = [int(start * decay_factor**i) for i in range(num_points)]
    index = 0

    while True:
        yield values[index]
        index = (index + 1) % num_points


# Example: Generate a sequence of 50 gradually decreasing integers from 4000 to around 2500
decay_sequence_generator = decay_generator(3500, 2500, 50)


class DataCollector:
    def __init__(self, stop_event):
        self.pressure_data = []
        self.time_data = []
        self.latest_value = None
        self.latest_time = None
        self.lock = threading.Lock()
        self.stop_event = stop_event
        self.sample_time = 5  # Sample every 5 seconds.
        max_storage = 1  # Store 1 day worth of data.

        self.deque_data = collections.deque(maxlen=int(max_storage*86400/self.sample_time))
        self.deque_time = collections.deque(maxlen=int(max_storage*86400/self.sample_time))

    def stop_collection(self):
        self.stop_event.set()

    def start_collection(self):
        self.stop_event.clear()

        chandle = ctypes.c_int16()
        status = {}
        chandle, status, noOfValues = OpenUnit(chandle, status)

        while not self.stop_event.is_set():
            # Simulate streaming data, e.g., from sensors or external source
            with self.lock:
                # Get pressure reading
                # adc = SingleReading(channel = 16)

                chandle, status, voltage = AverageReading(chandle, status, noOfValues)

                # adc = next(decay_sequence_generator)
                # mV = adc2volts(adc)
                # voltage = min(mV, 8.6) # If Voltage > 8.6, set it to 8.6. Shouldn't exceed 1000mbar.
                pressure_reading = volts2mbar(voltage)

                # Time of reading
                time_reading = format_time()

                self.latest_value = pressure_reading
                self.latest_time = time_reading
                self.deque_data.append(pressure_reading)
                self.deque_time.append(time_reading)
                self.save_to_file(pressure_reading, time_reading)

            # Wait 2 seconds
            self.stop_event.wait(timeout=self.sample_time)

        CloseUnit(chandle, status)
        print(status["closeUnit"])
        return 0

    def bot(self, bot):
        """
        Requires BOT_TOKEN.env file to be in same path as Python script.
        """
        self.stop_event.clear()
        print("BOT START")

        @bot.message_handler(commands=['pressure', 'p', 'P', 'Pressure'])
        def pressure_reponse(message):
            with self.lock:
                latest_value = "{:.2e}".format(self.latest_value)

            if latest_value is None:
                response = ("No Data Collected Yet")
                print('Bot Reply: Mo Data Collected Yet')
            else:
                response = f'Pressure: {latest_value} mbar'
                print(f'Bot Reply: Pressure: {latest_value} mbar')

            bot.reply_to(message, response)

        @bot.message_handler(commands=['end'])
        def end(message):
            self.stop_collection()

        def checker():
            if self.stop_event.is_set():  # If stop_event is set, terminate
                bot.stop_polling()
                print("Stopped polling")
                return 0

            # Run checker function again
            else:
                recur = Timer(self.sample_time, checker)
                recur.start()

        # Start checker function, which determined
        checker()

        # Start bot polling
        bot.polling(skip_pending=True, timeout=5)

    def get_all_data(self):
        """
        Returns list with copy of pressure_data and time_data.
        """
        with self.lock:
            return [[*self.deque_data.copy()], [*self.deque_time.copy()]]

    def get_latest_value(self):
        """
        Prints latest value
        """
        with self.lock:
            # print("{:.2e}".format(self.latest_value))
            return self.latest_value

    def get_latest_time(self):
        """
        Prints latest time
        """
        with self.lock:
            # print(self.latest_time)
            return self.latest_time

    def save_to_file(self, pressure_value, time_value, filename='pressure_data.txt'):
        with open(filename, 'a') as file:
            pressure_value = min(pressure_value, 1000)
            pressure = "{:.2e}".format(pressure_value)
            file.write(f"{pressure} {time_value}\n")
            # print(f"{pressure} {time_value}\n")


class App:
    def __init__(self, master):
        self.master = master
        self.master.title("PicoLog1216 Voltage-To-Pressure")
        self.after_id = None

        # Create telegram bot
        load_dotenv(dotenv_path="BOT_TOKEN.env")
        self.bot = telebot.TeleBot(os.getenv('BOT_TOKEN'))

        # Create a Stop Event to terminate Bot and PicoLog1216 Collection Threads
        self.stop_event = Event()

        # Set Event, as we only want this to be clear when the threads are running.
        self.stop_event.set()

        # Define our datacollector class, which has the Bot and PicoLog1216 Threads.
        self.data_collector = DataCollector(self.stop_event)

        """
        Create buttons:
            start_collection: starts data collection and telegram bot
            stop_collection: stops data collection and telegram bot
            get_latest_value: prints latest data
            time_range_entry:
            plot_button:
        """
        # Create Frame for buttons
        self.button_frame = tk.Frame(master)
        self.button_frame .grid(row=1, column=1, pady=10, padx=20, sticky='nw')

        self.start_collection_button = tk.Button(
            self.button_frame, text="Start Collection And Bot", command=self.start_collection)
        self.start_collection_button.grid(row=0, column=1, pady=10, sticky='nw')

        self.stop_collection_button = tk.Button(
            self.button_frame, text="Stop Collection And Bot", command=self.stop_collection)
        self.stop_collection_button.grid(row=1, column=1, pady=10, sticky='nw')

        self.get_latest_value_button = tk.Button(
            self.button_frame, text="Print Latest Value", command=self.get_latest_value)
        self.get_latest_value_button.grid(row=2, column=1, pady=5, sticky='nw')

        self.get_latest_value_button = tk.Button(
            self.button_frame, text="Print Latest Time", command=self.get_latest_time)
        self.get_latest_value_button.grid(row=2, column=2, pady=5, sticky='nw')

        self.time_range_label = tk.Label(self.button_frame, text="Time Range (seconds):")
        self.time_range_label.grid(row=3, column=1, pady=5, sticky='nw')

        self.plot_button = tk.Button(self.button_frame, text="Plot", command=self.select_datetime)
        self.plot_button.grid(row=5, column=1, sticky='n')

        """
        Allow user to customise input time units
        """
        self.datetime_variable = timedelta(hours=1)

        self.time_range_entry = ttk.Entry(self.button_frame)
        self.time_range_entry.insert(0, "01")

        # Configure validation to allow only non-negative integers
        vcmd = (self.master.register(self.validate_time_range), "%P")
        self.time_range_entry.config(validate="key", validatecommand=vcmd)

        self.time_range_entry.grid(row=4, column=1, padx=0, pady=5, sticky='nw')

        self.time_unit_var = tk.StringVar()
        self.time_unit_var.set('hours')  # Default selection
        self.time_unit_optionmenu = tk.OptionMenu(
            self.button_frame, self.time_unit_var, 'seconds', 'minutes', 'hours', 'days')
        self.time_unit_optionmenu.grid(row=4, column=2, padx=10, pady=5, sticky='nw')

        """
        Display latest data and time reading.
        """
        self.latest_data_text = tk.Text(self.button_frame, height=1, width=20, state='disabled')
        self.latest_data_text.grid(row=9, column=1, pady=5, sticky='nw')
        self.latest_data_label = tk.Label(self.button_frame, text="Latest Data")
        self.latest_data_label.grid(row=8, column=1, pady=5, sticky='nw')

        self.latest_time_text = tk.Text(self.button_frame, height=1, width=20, state='disabled')
        self.latest_time_text.grid(row=11, column=1, pady=5, sticky='nw')
        self.latest_time_label = tk.Label(self.button_frame, text="Latest Time")
        self.latest_time_label.grid(row=10, column=1, pady=5, sticky='nw')

        """
        Create our image frame, with another Frame for the interactive toolbar.
        """
        # Create frame for Figure to sit inside.
        self.image_frame = tk.Frame(master)
        self.image_frame.grid(row=1, column=4, pady=10, sticky='n')

        # Create Frame for Toolbar to sit inside.
        bottom = tk.Frame(self.image_frame)

        # Pack on the bottom, expanded and filled.
        bottom.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=tk.TRUE)

        # Create our figure.
        self.figure = Figure(figsize=(8, 5), dpi=100)

        # Create the canvas inside image_frame
        self.canvas = FigureCanvasTkAgg(master=self.image_frame, figure=self.figure)
        self.canvas.draw()

        # Create key press command, so that keyboard shortcuts activate toolbar
        def on_key_press(event):
            key_press_handler(event, self.canvas, self.toolbar)

        self.canvas.mpl_connect("key_press_event", on_key_press)

        # Create toolbar linked to canvas, inside image_frame.
        self.toolbar = NavigationToolbar2Tk(window=self.image_frame, canvas=self.canvas)
        self.toolbar.update()

        # Pack toolbar on bottom, left aligned.
        self.toolbar.pack(in_=bottom, side=tk.LEFT)

        # Get the current graph axis.
        self.ax = self.figure.gca()

        # Pack all the widgets.
        self.canvas.get_tk_widget().pack(side=tk.BOTTOM, fill=tk.BOTH, expand=tk.TRUE)

        self.master.protocol('WM_DELETE_WINDOW', lambda: self.confirm_exit(self.master)) # GUI exit protocol
        
    def confirm_exit(self, master):
        print("CLOSING")
        master.quit()
        print("DESTROYING")
        master.destroy()
        return

    def validate_time_range(self, new_value):
        try:
            # Ensure the first character is always "0"
            if new_value and new_value[0] != "0":
                return False

            # Attempt to convert the new value to an integer
            value = int(new_value)
            # Check if the value is non-negative
            return value >= 0
        except ValueError:
            # If conversion to int fails, return False (invalid input)
            return False

    def select_datetime(self):
        try:
            time_value = float(self.time_range_entry.get())
        except ValueError:
            print("Invalid input. Please enter a numeric value.")
            return

        time_unit = self.time_unit_var.get()
        # print(time_unit)

        if time_unit == 'seconds':
            delta = timedelta(seconds=time_value)
        elif time_unit == 'minutes':
            delta = timedelta(minutes=time_value)
        elif time_unit == 'hours':
            delta = timedelta(hours=time_value)
        elif time_unit == 'days':
            delta = timedelta(days=time_value)
        else:
            delta = timedelta(days=0)

        self.datetime_variable = datetime.now() - delta
        # print("Selected Datetime:", self.datetime_variable)

        # Create Plot
        self.plot_data()

    def plot_data(self):
        # Get data and timestamps
        all_data, all_timestamps = self.data_collector.get_all_data()

        # Convert timestamps into datetime objects
        datetime_objects = [datetime.strptime(timestamp, '%Y:%m:%d %H:%M:%S')
                            for timestamp in all_timestamps]

        # Find how far back we want to filter our data by. I.e., last 5 minutes or 5 hours etc.
        start_time = self.datetime_variable

        # Filter data within time range
        filtered_data = [data for data, timestamp in zip(
            all_data, datetime_objects) if start_time <= timestamp]
        filtered_time = [timestamp for data, timestamp in zip(
            all_data, datetime_objects) if start_time <= timestamp]

        if not filtered_data:
            print("No Filtered Data in this time range. Displaying over last 24 hours.")
            start_time = timedelta(days=1)
            return

        # Plot the filtered data
        self.ax.clear()

        # self.ax.plot(datetime_objects, all_data, marker='o', label='All Data')
        self.ax.plot(filtered_time, filtered_data, marker='o',
                     label=f'Pressure Over Last {float(self.time_range_entry.get())} {self.time_unit_var.get()}')
        self.ax.legend(loc='upper right')
        self.ax.set_yscale('log')

        # Additional plotting configurations (axis labels, formatting, etc.)
        self.figure.tight_layout(pad=3)
        self.ax.set_ylim(0.9*np.amin(filtered_data), 1.1*min(1e3, np.amax(filtered_data)))
        self.canvas.draw()

        """
        Update Latest value
        """
        latest_data = self.data_collector.get_latest_value()
        latest_data = "{:.2e}".format(latest_data)

        self.latest_data_text.config(state='normal')  # Enable the text widget for editing
        self.latest_data_text.delete('1.0', tk.END)  # Clear existing content
        self.latest_data_text.insert(tk.END, f"{latest_data}")  # Insert new content
        self.latest_data_text.config(state='disabled')  # Disable the text widget for editing

        latest_time = self.data_collector.get_latest_time()
        self.latest_time_text.config(state='normal')  # Enable the text widget for editing
        self.latest_time_text.delete('1.0', tk.END)  # Clear existing content
        self.latest_time_text.insert(tk.END, f"{latest_time}")  # Insert new content
        self.latest_time_text.config(state='disabled')  # Disable the text widget for editing

    def start_collection(self):
        self.collection_thread = threading.Thread(
            target=self.data_collector.start_collection, args=[])
        self.collection_thread.start()

        self.stop_event.wait(2)  # Wait 2 seconds

        self.telebot_thread = threading.Thread(target=self.data_collector.bot, args=[self.bot])
        self.telebot_thread.start()

        self.after_id = self.master.after(5000, self.update_data)

    def stop_collection(self):
        if self.stop_event.set():
            return

        self.data_collector.stop_collection()
        self.telebot_thread.join(5)
        self.collection_thread.join(5)
        print("Thread Ended")

        if self.after_id is not None:
            self.master.after_cancel(self.after_id)
            self.after_id = None
            self.start_collection_button.config(state=tk.NORMAL)
            self.stop_collection_button.config(state=tk.DISABLED)
        
        return

    def get_latest_value(self):
        self.data_collector.get_latest_value()

    def get_latest_time(self):
        self.data_collector.get_latest_time()

    def save_to_file(self):
        self.data_collector.save_to_file(self.data_collector.latest_value)

    def update_data(self):
        self.select_datetime()
        self.start_collection_button.config(state=tk.DISABLED)
        self.stop_collection_button.config(state=tk.NORMAL)
        self.after_id = self.master.after(5000, self.update_data)  # Update every 5 seconds


if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = App(root)
        # root.protocol("WM_DELETE_WINDOW", root.destroy)  # Handle window close event
        root.mainloop()
        print("Test")
        root.destroy()
    except Exception as e:
        print("Closing GUI")