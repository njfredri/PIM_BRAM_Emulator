import numpy as np
import math
###This class is intended to emulate just the BRAM. It will emulate the memory array and bit-serial periphery
###For now, it will do cycle counts, not necessarily logic (yet)
class BRAM():
    def __init__(self, num_col=160, num_row=128, col_muxing=4):
        self.PIM_mode = False
        self.num_ports = 2
        self.mem_array = np.zeros(shape=(num_col, num_row), dtype=np.bool)
        self.bit_width = num_col/col_muxing

        self.maxBRAMJumps = 9
        
        self.reg_file = np.zeros(shape=(self.bit_width*2)) #regular register file
        self.pipe_reg2 = np.zeros(shape=((self.bit_width*2)+1)) #register after networking
        self.pipe_reg2 = np.zeros(shape=((self.bit_width*2))) #register after opmux
        self.pipe_reg3 = np.zeros(shape=(self.bit_width)) #write-back register

        self.cycle_count = 0

    def three_cycle_op(self): #for addition, subtraction, and copy (just booth's)
        #read cycle
        self.cycle_count +=1
        #execute
        self.cycle_count +=1
        #writeback
        self.cycle_count +=1
    
    def two_cycle_op_iter(self):
        #execute
        self.cycle_count +=1
        #writeback/read
        self.cycle_count +=1

    def two_cycle_op_first_iter(self):
        #read
        self.cycle_count +=1
        #execute
        self.cycle_count +=1
        #writeback/read
        self.cycle_count +=1

    def addsub2op(self, bit_length:int, rownum1:int , rownum2:int, rowdes:int):
        bitcnt = 0
        while bitcnt < bit_length:
            self.three_cycle_op()
            bitcnt += 4
    
    def add1op(self, bit_length:int):
        bitcnt = 4
        self.two_cycle_op_first_iter()
        while bitcnt < bit_length:
            self.two_cycle_op_iter(self)
            bitcnt += 4
    
    def intraAcc(self, bit_length, num_words):
        num_iter = math.ceil(math.log2(num_words))
        for i in range(num_iter):
            self.add1op(bit_length)
    
    def travel_data(self, bit_length:int, distance:int): #move data close enough to be operated on in an inter-BRAM operation
        dis = distance
        while dis > 9:
            self.add1op(bit_length) #perform a copy across 9 BRAMs
            dis -= 9
        return

    def interAcc(self, bit_length:int, num_BRAMS:int):
        words = num_BRAMS
        distance = 1
        while words > 1:
            to_travel = 1
            self.travel_data(bit_length, to_travel) #move data close enough to perform the 1-op addition
            self.add1op(bit_length)
            words = math.ceil(words/2)

    def mult(self, bit_length:int, mult_length:int):
        for i in range(mult_length):
            #Spend 1 CC to read the multiplier bits
            self.cycle_count += 1
            #Perform the 2-op add/sub/cpy between the accumulator and multiplicand
            self.addsub2op(bit_length=bit_length, rownum1=0, rownum2=0, rowdes=0)
    
    def GEMV(self, bit_length:int, acc_length:int, mult_length:int, num_words:int):
        #perform element-wise accumulation
        self.mult(bit_length, mult_length)
        #perform intra-BRAM accumulation
        num = num_words
        if num >= 40:
            self.intraAcc(acc_length, 40)
        else:
            self.intraAcc(acc_length, num)
        num = math.ceil(num/40)
        #perform inter-BRAM accumulation
        if(num > 1):
            self.interAcc(acc_length, num)
            num = 1
        #perform addition (adding the bias)
        self.addsub2op(acc_length, 0,0,0)

    def offloadToDSPs(self, bit_length:int):
        #immediately read from data port B using the output shift-reg
        self.cycle_count += 1 #perform the bit-parallel operation using the DSP
        #start writing back in bit-serial form
        self.cycle_count += bit_length
        

        
    
        

