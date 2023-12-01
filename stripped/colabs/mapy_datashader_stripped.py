"""
<a href="https://colab.research.google.com/github/PiotrMaciejKowalski/BigData2024Project/blob/Narzdzie-do-wizualizacji-na-mapach/mapy_datashader.ipynb" target="_parent"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/></a>
"""

!pip install datashader


!pip install holoviews hvplot colorcet


!pip install geoviews


import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt


# import doinstalowanych pakietów
import datashader as ds
import datashader.transfer_functions as tf
import colorcet as cc
import holoviews as hv
from holoviews.operation.datashader import datashade
import geoviews as gv
import geoviews.tile_sources as gts
from holoviews import opts


"""
Wczytujemy stworzony wcześniej plik z danymi na jeden miesiąc:
"""

from google.colab import drive


drive.mount('/content/drive')


"""
Ładujemy plik utworzony wcześniej, zawierający dane z grudnia 2022. Plik znajduje się we [wspólnym zasobie na dysku Google](https://drive.google.com/file/d/1BlcXB-GsbzeBVWKqYxOvltoEknGivoKK/view?usp=drive_link).
"""

df = pd.read_csv('/content/drive/MyDrive/BigMess/NASA/nasa_dec22_loc.csv')


df


"""
Definiujemy funkcję, która umożliwi tworzenie własnych zakresów kolorów użytych do map:
"""

'''
Funkcja jako argumenty bierze listę wartości określających granice przedziałów liczbowych, które
będą określać jak dla rozważanego parametru mają zmieniać się kolory punktów, których lista stanowi
drugi argument funkcji.
'''
def get_colormap(values: list, colors_palette: list, name = 'custom'):
    values = np.sort(np.array(values))
    values = np.interp(values, (values.min(), values.max()), (0, 1))
    cmap = mpl.colors.LinearSegmentedColormap.from_list(name, list(zip(values, colors_palette)))
    return cmap


"""
Zdefiniujmy funkcję generującą mapę i zapisującą ją w formacie .html:
"""

def plot_map(df: pd.DataFrame, parameter_name: str, colormap: mpl.colors.LinearSegmentedColormap,
             point_size: int = 8, width: int = 900, height: int = 600, alpha: float = 1,
             bgcolor: str = 'white'):

    gdf = gv.Points(df, ['lon', 'lat'], [parameter_name]) # obiekt zawierający punkty
    tiles = gts.OSM # wybór mapy tła, w tym wypadku OpenStreetMap

    # łączenie mapy tła z punktami i ustawienie wybranych parametrów wizualizacji
    map_with_points = tiles * gdf.opts(
        color=parameter_name,
        cmap=colormap,
        size=point_size,
        width=width,
        height=height,
        colorbar=True,
        toolbar='above',
        tools=['hover', 'wheel_zoom', 'reset'],
        alpha=alpha # przezroczystość
    )

    map_with_points.opts(bgcolor=bgcolor)

    # zapis mapy do pliku .html
    output_filename = f'output_map_{parameter_name}.html'
    hv.save(map_with_points, output_filename)


"""
Tworzymy pierwszą mapę, w tym wypadku dla parametru GVEG związanego z poziomem roślinności:
"""

colormap_GVEG = get_colormap([0, max(df.GVEG.values)], ['yellow', 'darkgreen'])

plot_map(df=df, parameter_name='GVEG', colormap=colormap_GVEG, alpha=0.5)


"""
Druga mapa, tym razem dla parametru Rainf określającego poziom opadów deszczu:
"""

colormap_Rainf = get_colormap([0, max(df.Rainf.values)/2, max(df.Rainf.values)], ['white', 'blue', 'black'])

plot_map(df=df, parameter_name='Rainf', colormap=colormap_Rainf, point_size=5)


"""
Trzecia mapa dla AvgSurfT, tj. średniej temperatury powierzchni:
"""

colormap_AvgSurfT = 'cet_rainbow_bgyr_10_90_c83'

plot_map(df=df, parameter_name='AvgSurfT', colormap=colormap_AvgSurfT, point_size=5, alpha=0.7)


