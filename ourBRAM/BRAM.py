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
        self.num_pes = num_col/col_muxing
        self.maxBRAMJumps = 9
        
        # # self.reg_file = np.zeros(shape=(self.bit_width*2)) #regular register file
        # self.pipe_reg2 = np.zeros(shape=((self.bit_width*2)+1)) #register after networking
        # self.pipe_reg2 = np.zeros(shape=((self.bit_width*2))) #register after opmux
        # self.pipe_reg3 = np.zeros(shape=(self.bit_width)) #write-back register

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
            self.two_cycle_op_iter()
            bitcnt += 4

    def mult(self, bit_length:int, mult_length:int):
        for i in range(mult_length):
            #Spend 1 CC to read the multiplier bits
            self.cycle_count += 1
            #Perform the 2-op add/sub/cpy between the accumulator and multiplicand
            self.addsub2op(bit_length=bit_length, rownum1=0, rownum2=0, rowdes=0)
    
    # def GEMV(self, bit_length:int, acc_length:int, mult_length:int, num_words:int):
    #     #perform element-wise accumulation
    #     self.mult(bit_length, mult_length)
    #     #perform intra-BRAM accumulation
    #     num = num_words
    #     if num >= 40:
    #         self.intraAcc(acc_length, 40)
    #     else:
    #         self.intraAcc(acc_length, num)
    #     num = math.ceil(num/40)
    #     #perform inter-BRAM accumulation
    #     if(num > 1):
    #         # print('here')
    #         self.interAcc(acc_length, num)
    #         num = 1
    #     #perform addition (adding the bias)
    #     self.addsub2op(acc_length, 0,0,0)

    def offloadToDSPs(self, bit_length:int):
        #immediately read from data port B using the output shift-reg
        self.cycle_count += 1 #perform the bit-parallel operation using the DSP
        #start writing back in bit-serial form
        self.cycle_count += bit_length
        

# if __name__ == "__main__":
#     bram1 = BRAM()
#     for i in range(21):
#         bram1.GEMV(bit_length=8, acc_length=8, mult_length=8, num_words=768)
#     print(bram1.cycle_count)
DEBUG=True
def print_debug(message: str):
    if(DEBUG):
        print(message)

class PIM_FPGA():
    def __init__(self, base_prec=4, inc_acc_prec=False):
        self.num_bram = 2423
        self.bram = BRAM()
        self.pes_per_bram = self.bram.num_pes
        self.base_prec = base_prec
        self.increment_acc = inc_acc_prec

    def intraAcc(self, num_words, bit_precision, inc_acc_prec=False):
        acc_prec = bit_precision #account for increasing precision req for acc
        num_iter = math.ceil(math.log2(num_words))
        for i in range(num_iter):
            if(inc_acc_prec): 
                acc_prec += 1
            self.bram.add1op(acc_prec)
        if(inc_acc_prec): 
                acc_prec -= 1
        return acc_prec
    
    def travel_data(self, bit_length:int, distance:int): #move data close enough to be operated on in an inter-BRAM operation
        dis = distance
        while dis > 9:
            # print("must copy data")
            self.bram.add1op(bit_length) #perform a copy across 9 BRAMs
            # print_debug("performing copy")
            dis -= 9
        return
    
    def interAcc(self, num_BRAMS:int, bit_precision:int, inc_acc_prec=False):
        words = num_BRAMS
        distance = 1
        to_travel = 1
        acc_precision = bit_precision
        while words > 1:
            if(inc_acc_prec):
                acc_precision += 1
            self.travel_data(acc_precision, to_travel) #move data close enough to perform the 1-op addition
            self.bram.add1op(acc_precision)
            words = math.ceil(words/2)
            to_travel *= min(2,math.ceil(num_BRAMS/2))

        return acc_precision

    def GEMV(self, mrow, mcol, vsize, mprec, vprec, bias_prec, inc_acc_prec=False):
        # print(mcol, vsize)
        assert mcol==vsize
        
        #if the GEMV operation is too large, break it up into peices
        num_req_BRAM_for_rows = mrow
        num_req_BRAM_for_acc  = math.ceil(mcol / self.pes_per_bram)
        if num_req_BRAM_for_acc > self.num_bram:
            print("error, need ", num_req_BRAM_for_acc, "BRAMs for just accumulation")
            exit(1)

        num_req_BRAM = num_req_BRAM_for_rows * num_req_BRAM_for_acc
        num_runs = 1 #number of smaller GEMV operations to perform the current operation
        if num_req_BRAM > self.num_bram:
            rows_per_run = math.floor(self.num_bram / num_req_BRAM_for_acc)
            num_runs = math.ceil(mrow / rows_per_run)
            #perform all those smaller GEMV runs
            for i in range(num_runs):
                self.GEMV(rows_per_run, mcol, vsize, mprec, vprec, bias_prec, inc_acc_prec=inc_acc_prec)
        else: #otherwise, just perform GEMV operation as usual
            #perform element-wise multiplication
            self.bram.mult(vprec, mprec)
            #perform intra-BRAM accumulation
            product_prec = (vprec+mprec)
            acc_precision = product_prec + math.ceil(math.log2(mcol)) + 1
            if(inc_acc_prec==True):
                acc_precision = product_prec #start low. Increase as you go

            # print("og acc precision ", acc_precision)

            num_words = mcol
            if num_words >= 40:
                acc_ret = self.intraAcc(40, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec==True):
                    acc_precision = acc_ret #start low. Increase as you go
            else:
                acc_ret  = self.intraAcc(num_words, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec==True):
                    acc_precision = acc_ret #start low. Increase as you go
            num_words = math.ceil(num_words/40)
            #perform inter-BRAM accumulation (if needed)
            if num_words > 1:
                acc_ret = self.interAcc(num_words, acc_precision,  inc_acc_prec=inc_acc_prec)
                num_words = 1
                if(inc_acc_prec==True):
                    acc_precision = acc_ret #start low. Increase as you go

            #perform addition (add the bias)
            self.bram.addsub2op(bias_prec, 0,0,0)
            # print("final acc precision ", acc_precision)
    
    def GEMV_batched(self, mrow, mcol, vsize, num_patches, mprec, vprec, bias_prec, inc_acc_prec=False):
        for patch in range(num_patches):
            self.GEMV(mrow, mcol, vsize, mprec, vprec, bias_prec, inc_acc_prec=inc_acc_prec)

    

    def dotproduct(self, mrow, mcol, vsize, mprec, vprec, inc_acc_prec=False):
        assert mcol==vsize
        #if the GEMV operation is too large, break it up into peices
        num_req_BRAM_for_rows = mrow
        num_req_BRAM_for_acc  = math.ceil(mcol / self.pes_per_bram)
        if num_req_BRAM_for_acc > self.num_bram:
            print("error, need ", num_req_BRAM_for_acc, "BRAMs for just accumulation")
            exit(1)

        num_req_BRAM = num_req_BRAM_for_rows * num_req_BRAM_for_acc
        num_runs = 1 #number of smaller GEMV operations to perform the current operation
        if num_req_BRAM > self.num_bram:
            rows_per_run = math.floor(self.num_bram / num_req_BRAM_for_acc)
            num_runs = math.ceil(mrow / rows_per_run)
            #perform all those smaller GEMV runs
            for i in range(num_runs):
                self.dotproduct(rows_per_run, mcol, vsize, mprec, vprec, inc_acc_prec=inc_acc_prec)
        else: #otherwise, just perform GEMV operation as usual
            #perform element-wise multiplication
            self.bram.mult(vprec, mprec)
            #perform intra-BRAM accumulation
            product_prec = (vprec+mprec)
            acc_precision = product_prec + math.ceil(math.log2(mcol)) + 1
            if(inc_acc_prec):
                acc_precision = product_prec #start low. Increase as you go

            num_words = mcol
            if num_words >= 40:
                acc_ret = self.intraAcc(40, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec):
                    acc_precision = acc_ret #start low. Increase as you go
            else:
                acc_ret  = self.intraAcc(num_words, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec):
                    acc_precision = acc_ret #start low. Increase as you go

            num_words = math.ceil(num_words/40)
            #perform inter-BRAM accumulation (if needed)
            if num_words > 1:
                self.interAcc(num_words, acc_precision, inc_acc_prec=inc_acc_prec)
                num_words = 1

    def dotproductmm(self, mrow, mcol, m2row, m2col, mprec, m2prec, inc_acc_prec=False):
        assert mcol==m2row
        #base dotp operation = <mrow,mcol> * <m2col>. Do that dotp m2row-times
        base_dotp_num_bram = math.ceil(mcol/40)*mrow
        dotps_at_a_time = math.floor(self.num_bram / base_dotp_num_bram)
        dotp_iterations = math.ceil(m2row / dotps_at_a_time)
        for i in range(dotp_iterations): #perform all mv dotp operations
            self.dotproduct(mrow, mcol, m2col, mprec, m2prec, inc_acc_prec=inc_acc_prec)
    
    def dotproductmm_batched(self, mrow, mcol, m2row, m2col, mprec, m2prec, num_batches, inc_acc_prec=False):
        # print(mcol, m2row)
        assert mcol==m2row
        #base dotp operation = <mrow,mcol> * <m2col>. Do that dotp m2row-times. 
        #Then perform the matrix-matrix dotp num_batches-times.
        base_dotp_num_bram = math.ceil(mcol/40)*mrow
        dotps_at_a_time = math.floor(self.num_bram / base_dotp_num_bram)
        dotp_iterations = math.ceil(m2col * num_batches / dotps_at_a_time) 
        for i in range(dotp_iterations): #perform all mv dotp operations
            self.dotproduct(mrow, mcol, m2row, mprec, m2prec, inc_acc_prec=inc_acc_prec)
    
