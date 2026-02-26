import numpy as np
import math

DEBUG=True
def print_debug(message: str):
    if(DEBUG):
        print(message)

class BRAMAC():
    def __init__(self, precision:int, double_pumped: bool):
        self.prec = precision
        self.p = 40 #p = number of parallel mac2 operations
        self.maxdp = 2048
        self.mac2_startup =  2
        self.mac2_del = 5
        self.BRAM_rows = 128
        if precision==2:
            self.p = 80
            self.maxdp = 16
            #can only perform up to 8 MAC2's before needing to store accumulator
            #somewhere else
            self.mac2_del = 5 #num cc's to perform mac2
        elif precision==4:
            self.p = 40
            self.maxdp = 256
            self.mac2_del = 7
        elif precision==8:
            self.p = 20
            self.maxdp = 2048
            self.mac2_del = 11
        else:
            raise Exception("error, unsupported precision")
        
        self.rd_acc_delay = 8 #delay to read accumulator

        if double_pumped:
            self.p /= 2
            self.rd_acc_delay = 4
            self.mac2_del /= 2
        self.cc = 0
        self.lastop = 'none'
    
    def mac2(self):
        cc = 0
        if self.lastop != 'mac2':
            cc += self.mac2_startup
            self.lastop = 'mac2'
        cc += self.mac2_del
        return cc

    def readacc(self):
        cc = self.rd_acc_delay
        self.lastop = 'read'
        return cc

#Note: Because BRAMAC's weight rows are accumulated, they map more directly to "columns" in gemv operations

class PIM_FPGA():
    def __init__(self, precision, double_pumped):
        self.bram = BRAMAC(precision=precision, double_pumped=double_pumped)
        self.num_bram = 2423
        return
    
    def dotpmv(self, inrow, incol, in2row, numBRAM_split):
        numBRAM_for_rows = math.ceil(inrow / self.bram.p)
        numBRAMs_for_cols = numBRAM_split
        numBRAMs_required = numBRAM_for_rows*numBRAMs_for_cols
        if(numBRAMs_required > self.num_bram):
            print_debug("splitting up dotpmv operation")
            #split up by rows as those are relatively independent
        else:


    def dotpmv_explore(self, inrow, incol, in2row):
        assert incol == in2row
        numBRAM_split = 1 #number of BRAMs that columns are split between
        delays = []
        while numBRAM_split < inrow:
