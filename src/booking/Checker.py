from pathlib import Path
from datetime import timedelta
from typing import List

import pandas as pd
import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    import sys

    sys.path.append(str(PROJECT_DIR))

from src.HostInfo import HostInfo, BookingTime, BasicCapability, ScheduleDF


class Checker(HostInfo):
    # deploy_info: HostInfo.deploy_info
    # cap_config: HostInfo.cap_config
    # users_config: HostInfo.users_config

    # booking: HostInfo.booking
    # using: HostInfo.using
    # used: HostInfo.used

    booked_df: pd.DataFrame
    user_booking_range_df: pd.DataFrame
    user_booking_time: BookingTime
    # self used flag
    __test_flag: bool = False

    def __init__(
        self,
        deploy_yaml: Path = PROJECT_DIR / 'cfg/host_deploy.yaml',
        booking_csv: Path = PROJECT_DIR / 'jobs/booking.csv',
        using_csv: Path = PROJECT_DIR / 'jobs/using.csv',
        used_csv: Path = PROJECT_DIR / 'jobs/used.csv',
    ) -> None:
        super().__init__(deploy_yaml, booking_csv, using_csv, used_csv)
        self.booked_df = ScheduleDF.concat(self.booking.df, self.using.df)

    def check_student_id(self, student_id: str) -> bool:
        return student_id in self.users_config.ids.keys()

    def get_user_max_cap(self, student_id: str) -> BasicCapability:
        # search if student.id in self.cap_config.max_custom_capability and return it or return max_default_capability
        if student_id in self.cap_config.max_custom_capability.keys():
            if self.__test_flag:
                print(student_id, ':max_custom_capability')
            return self.cap_config.max_custom_capability[student_id]
        else:
            if self.__test_flag:
                print(student_id, ':max_default_capability')
            return self.cap_config.max_default_capability

    def check_cap4time(self, cap_info: BasicCapability, booking_time: BookingTime) -> bool:
        '''check if cap_info satisfy the capability during booking_time'''
        # * only compare gpus
        gpu_np = self.__booking_to_gpu_nparray(booking_time)
        max_using_count = 0  # store max using gpus in the same time block
        for i in range(len(gpu_np[0])):  # run every time block
            if np.count_nonzero(gpu_np[:, i] == 1) > max_using_count:  # if there is more count, replace max_using_count
                max_using_count = np.count_nonzero(gpu_np[:, i] == 1)
        # return ((max) - (how many been used) >= (how many cap_info asked)) -> boolean
        if self.__test_flag:
            print(f'{self.cap_config.max.gpus} - {max_using_count} >= {cap_info.gpus}')
        return self.cap_config.max.gpus - max_using_count >= cap_info.gpus

    def check_forward_port4time(self, forward_port: int, booking_time: BookingTime) -> bool:
        return False if forward_port in list(self.__find_book_time_csv(booking_time).loc[:, 'forward_port']) else True

    def get_best_gpu_ids(self, gpus: int, booking_time: BookingTime) -> List[int]:
        # * full up the forward gpu, so offer from the lower id gpus
        '''
        counting every gpu using time block -> gpu_used_count:[] (index = gpu.id, value = the gpu using time block)
        assign_gpu:[]       # the result gpu list
        extend gpu_used_count[==0] into assign_gpu
        if len(assign_gpu) < gpus
        extend gpu_used_count[==1] into assign_gpu
        and so on...
        until len(assign_gpu) > gpus: break
        assign_gpu = assign_gpu[:gpus]
        assign_gpu.sort()
        return assign_gpu
        '''
        gpu_np = self.__booking_to_gpu_nparray(booking_time=booking_time)
        # counting every gpu using time block (index = gpu.id, value = the gpu using time block)
        gpu_used_count = gpu_np.sum(axis=1)
        for i in range(self.cap_config.max.gpus):
            gpu_used_count[i] = np.count_nonzero(gpu_np[i] != 0)

        # ! is necessary do this?
        # assign_gpus = []  # the result gpu list
        # for i in range(int(max(gpu_used_count))):
        #     assign_gpus.extend(np.where(gpu_used_count == i)[0])
        #     if len(assign_gpus) >= gpus:
        #         break
        # assign_gpus = assign_gpus[:gpus]  # make sure only require number of gpus in assign_gpus
        # assign_gpus.sort()  # sort assign_gpus

        assign_gpus = gpu_used_count.argsort()[:gpus].tolist()

        return assign_gpus

    def check_forward_port_empty(self, user_id: str, forward_port: int) -> bool:
        # check is forward_port empty (occupy = False, empty = True)
        for k, v in self.users_config.ids.items():
            if forward_port == v.forward_port and k != user_id:
                return False
        return True

    def check_image_isexists(self, image: str) -> bool:
        return image in self.deploy_info.images

    def __find_book_time_csv(self, booking_time: BookingTime) -> pd.DataFrame:
        # sort Dataframe by 'start'
        # find the first value >= booking_time.start
        # drop earlier
        # repeat for 'end'

        if hasattr(self, 'user_booking_time'):
            if (
                hasattr(self, 'user_booking_range_df')
                and booking_time.end == self.user_booking_time.end
                and booking_time.start == self.user_booking_time.start
            ):
                return self.user_booking_range_df

        df = self.booked_df
        # sort data
        df = df.sort_values(by='start')
        df = df.loc[df['start'] < booking_time.end]  # keep which is start when book end #　start time smaller than my end time
        df = df.sort_values(by='end')
        df = df.loc[df['end'] > booking_time.start]  # keep which is not end when book start # end time bigger then my start time

        self.user_booking_range_df = df.reset_index(drop=True, inplace=False)
        self.user_booking_time = booking_time

        return self.user_booking_range_df

    def __booking_to_gpu_nparray(self, booking_time: BookingTime) -> np.ndarray:
        # this func turn booking information into gpus-time(30min) list
        n = (booking_time.end - booking_time.start) // timedelta(minutes=30)  # calculate cut booking time into n block
        gpu_np = np.zeros((self.cap_config.max.gpus, n))  # [gpu_id, time_block]
        csv = self.__find_book_time_csv(booking_time)
        for i in range(len(csv.index)):
            book_time = BookingTime()  # already booked information in csv
            book_time.start = csv.at[i, 'start']
            book_time.end = csv.at[i, 'end']
            if book_time.start < booking_time.start:  # if book_time is started before booking_time
                # only need to find where book_time end
                if book_time.end > booking_time.end:
                    # user i is using gpus fully during booking_time
                    for j in csv.at[i, 'gpus']:
                        gpu_np[j, :] = 1
                else:
                    # book_time end during booking_time
                    # find how many time block is using
                    using_block = (book_time.end - booking_time.start) // timedelta(minutes=30)
                    for j in csv.at[i, 'gpus']:
                        gpu_np[j, :using_block] = 1
            else:
                # book_time is starting during booking_time
                if book_time.end > booking_time.end:
                    # book_time end after booking_time end
                    # mark book_time.start ~ booking_time.end
                    non_using_block = (book_time.start - booking_time.start) // timedelta(minutes=30)
                    for j in csv.at[i, 'gpus']:
                        gpu_np[j, non_using_block:] = 1
                else:
                    # book_time end during booking_time
                    # find how many time block is using
                    using_block = (book_time.end - booking_time.start) // timedelta(minutes=30)
                    non_using_block = (book_time.start - booking_time.start) // timedelta(minutes=30)
                    for j in csv.at[i, 'gpus']:
                        gpu_np[j, non_using_block:using_block] = 1
        return gpu_np
