from typing import List, Optional, Union

from numpy import ndarray

class DF:
    def __init__(self, sr: int, fft_size: int, nb_bands: int, min_nb_erb_freqs: int): ...
    def analysis(self, input: ndarray) -> ndarray: ...
    def synthesis(self, input: ndarray) -> ndarray: ...
    def erb_widths(self) -> ndarray: ...
    def fft_window(self) -> ndarray: ...
    def reset(self) -> None: ...

def erb(input: ndarray, erb_fb: Union[ndarray, List[int]], db: Optional[bool]) -> ndarray: ...
def erb_inv(input: ndarray, erb_fb: Union[ndarray, List[int]]) -> ndarray: ...
def erb_norm(erb: ndarray, alpha: float, state: Optional[ndarray]) -> ndarray: ...
def unit_norm(spec: ndarray, alpha: float, state: Optional[ndarray]) -> ndarray: ...
def unit_norm_init(num_freq_bins: int) -> ndarray: ...