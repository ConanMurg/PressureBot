# PressureBot
Python Code for interfacing with a Telegram Bot. The python code samples the Analog Voltage output from a Vacuum Gauge, using a PicoLog Data Logger 1216, and converts the voltage into a pressure reading in mbar.

# Hardware
- Vacuum Display: Leybold Display Two Vacuum Display.
- Vacuum Gauage: PENNINGVAC PTR 90.
- Data Logger: Pico Log Data Logger 1216 (henceforth, PL1216).

The Analog Output from the Vacuum Display ranges from 0 to 10 V. The PL1216 only measure between -2.5 and 2.5V, and so a potential divider circuit is required on the Small Terminal Board. The R1 and R2 values chosen for our potential dividor must be selected to give a ratio of ~ 4.1, where $V_{out} = \frac{R2}{(R1+R2} * V_{in}$ so that the 10V input voltage is scaled to 2.5V. A potential dividor circuit is pictured below for the readers benefit.

![image](https://github.com/ConanMurg/PressureBot/assets/74504288/812f1dee-ebed-40c2-a448-44c04809f832)

The Small Terminal Board for the PL1216 has a [document](https://www.picotech.com/download/manuals/picolog-1000-series-small-terminal-board-users-guide.pdf) that outlines how to solder resistors to create a potential dividor for each input channel. I chose channel 16 as my input channel, and must therefore select to solder R2 onto position R32, and R1 onto position R31 on the board. 

![image](https://github.com/ConanMurg/PressureBot/assets/74504288/b990f60c-9ab2-4278-a881-ac7e67fb1172)

Specifically, R31 = 11.99 kOhm and R32 = 3.894 kOhm. 

# Voltage to Pressure Conversion
The voltage from the PTR90 can be converted to pressure using the following conversions, taken from the [PTR90 data sheet](https://www.idealvac.com/files/manuals/Leybold-PTR90-Gauge-Specs-Data-Manual.pdf).

![image](https://github.com/ConanMurg/PressureBot/assets/74504288/59513b23-fcd2-4b1b-a370-49653a325c83)

Therefore, for voltage to mbar: $10^{1.667* V-11.33}$, where V is the input voltage. However, as we have a potential divider, we must first scale the measured PL1216 voltage by our potential divider ratio of 4.1. Finally, the conversion from the PL1216 reading, to mbar is given by $10^{1.667* 4.1 * V-11.33}$.

# Requirements
pip install picosdk

