# -*- coding: utf-8 -*-
"""Klasyfikacja_drzewa_decyzyjne.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1t-03doL-wotOGP2d6P_akvN6zFqLdd0O

# Klasyfikacja z wykorzystaniem modeli opartymi o drzewa decyzyjnyjne

## Budowa modeli drzew decyzyjnych

**Cel**:

Celem jest zbudowanie modeli do klasyfikacji czy wskazany punkt lokalizacyjny ze zbioru danych NASA jest: pustynia, stepem lub innym obszarem. Zbudowane zostana trzy rodzaje modeli:

* Detekcja pustynia - step - inne
* Detekcja pustynia - niepustynia
* Detekcja step - niestep

Dla kazdego z miesiecy powstanie jeden model kazdego rodzaju.

**Proba danych**:

Dane wykorzystane do modelowania zostały stworzone po przez połączenie dwoch zbiorow danych:

* 1193 lokalizacji *lon* i *lat* z określoną flagą 0, 1 w kolumnach *pustynia* lub *step* (reczna adnotacja)
* danych NASA w podziale na miesiące. Od *pazdziernika 2022* do  *wrzesnia 2023*

**Metoda**:

Do modelowania uzyto metody drzew decyzyjnych.

### Import bibliotek oraz utorzenie srodowiska pyspark
"""

!pip install datashader
!pip install holoviews hvplot colorcet
!pip install geoviews

# Commented out IPython magic to ensure Python compatibility.
!git clone https://github.com/PiotrMaciejKowalski/BigData2024Project.git
# %cd BigData2024Project
!git checkout main
# %cd ..

!chmod 755 /content/BigData2024Project/src/setup.sh
!/content/BigData2024Project/src/setup.sh

from typing import List, Optional, Tuple
import pickle
import pandas as pd
import numpy as np
import matplotlib.colors as mpl_colors
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn import tree
from sklearn.ensemble import RandomForestClassifier
from sklearn.base import BaseEstimator
from sklearn.metrics import confusion_matrix, classification_report, accuracy_score, recall_score, precision_score, f1_score
from sklearn.model_selection import train_test_split, GridSearchCV
from imblearn.over_sampling import RandomOverSampler, SMOTE
from lightgbm import LGBMClassifier
import datashader as ds
import datashader.transfer_functions as tf
import colorcet as cc
import holoviews as hv
from holoviews.operation.datashader import datashade
import geoviews as gv
import geoviews.tile_sources as gts
from holoviews import opts
from IPython.display import IFrame
from bokeh.plotting import show, output_notebook

from google.colab import drive
import sys

drive.mount('/content/drive')

sys.path.append('/content/BigData2024Project/src')

from start_spark import initialize_spark
initialize_spark()

from pyspark.sql import SparkSession
from big_mess.loaders import default_loader, load_single_month, load_anotated, save_to_csv, preprocessed_loader

spark = SparkSession.builder\
        .master("local")\
        .appName("Colab")\
        .config('spark.ui.port', '4050')\
        .getOrCreate()

"""### Przygotowanie danych

Na podstawie wczesniej przygotowanych plikow .csv z anotowanymi danymi dla kazdego miesiaca tworzymy liste data framow.
"""

list_of_files = [
   f'nasa_anotated_{year}{month:02d}.csv'
   for year, month
   in [ (2023, m) for m in range(1,10) ]
   +  [ (2022, m) for m in range(10,13) ]
]

list_of_anotated_data = [preprocessed_loader(spark, '/content/drive/MyDrive/BigMess/NASA/Modele/Klasyfikacja/Anotated_data_12m/' + file) for file in list_of_files]

list_of_df_all = [anotated_data.toPandas() for anotated_data in list_of_anotated_data]

"""Dodanie do danych z kazdego miesiaca kolumny *klasa* z nastepujacym oslownikowaniem:

* **1** - pustynia
* **2** - step
* **3** - inne
"""

for df in list_of_df_all:
  df['klasa'] = np.where(
                        df['pustynia'] == 1, 1, np.where(
                        df['step'] == 1, 2, 3)
                        )

"""Przykladowa ramka danych."""

list_of_df_all[0].head()

"""Liczebnosci poszczegolnych klas w probce."""

{1:list_of_df_all[0]['pustynia'].sum(), 2:list_of_df_all[0]['step'].sum() , 3:list_of_df_all[0]['pustynia'].count() - list_of_df_all[0]['pustynia'].sum()- list_of_df_all[0]['step'].sum()}

"""Lista z danymi z kazdego miesiaca, do wizualizacji na mapach."""

list_df_months = [load_single_month(spark, year=year, month=month).toPandas() for year, month in [(2023, m) for m in range(1, 10)] + [(2022, m) for m in range(10, 13)]]

"""#### Wydzielenie zbiorow danych

Wydzielenie danych z etykietami do odpowiednich modeli oraz przygotowanie listy ramek danych z cechami badanych obszarow.

Cechy:

* **GVEG** - wskaznik roslinnosci
* **Rainf** - wskaznik opadow deszczu
* **Evap** - wskaznik calkowitej ewapotranspiracji
* **AvgSurfT** - wskaznik sredniej temperatury powierzchni ziemi
* **Albedo** - wskaznik albedo
* **SoilT_40_100cm** - wskaznik temperatury gleby w warstwie o glebokosci od 40 do 100 cm
* **PotEvap** - wskaznik potencjalnej ewapotranspiracji
* **RootMoist** - wilgotnosć gleby w strefie korzeniowej (parowanie, ktore mialoby miejsce, gdyby dostepne bylo wystarczajace zrodlo wody)
* **SoilM_100_200cm** - wilgotnosc gleby w warstwie o glebokosci od 100 do 200 cm
"""

y_m1 = list_of_df_all[0]['klasa']
y_m2 = list_of_df_all[0]['pustynia']
y_m3 = list_of_df_all[0]['step']

list_of_df = [df.loc[:,'Rainf':'SoilM_100_200cm'] for df in list_of_df_all]

"""#### Definiowanie funkcji"""

def create_models(params_gs: dict, list_of_df: List[pd.DataFrame], scoring:str = 'accuracy') -> tuple[List, List]:
  '''
  The function uses GridSearch to create DecisionTreeClassifier models. Returns a tuple of lists: ([models], [parameters]).
  '''
  list_params = []
  list_of_models = []
  number_of_data = len(list_of_df)

  for i in range(number_of_data):
    #GridSearch
    gs = GridSearchCV(tree.DecisionTreeClassifier(random_state = 2024), cv = 5, param_grid = params_gs, scoring = scoring)
    gs.fit(list_of_df[i][0], list_of_df[i][1])
    list_params.append(gs.best_params_)
    #Create
    list_of_models.append(tree.DecisionTreeClassifier(random_state = 2024, **list_params[i]))
    #Fit
    list_of_models[i].fit(list_of_df[i][0], list_of_df[i][1])

  return list_of_models, list_params

def summary_model(model: BaseEstimator, X:pd.DataFrame, y:pd.DataFrame, labels_names: List) -> None:
  '''
  The function displays the confusion matrix for the model.
  '''
  y_pred = model.predict(X)
  cf_matrix = confusion_matrix(y, y_pred)
  group_counts = ["{0:0.0f}".format(value) for value in cf_matrix.flatten()]
  group_percentages = ["{0:.2%}".format(value) for value in cf_matrix.flatten()/np.sum(cf_matrix)]
  labels = [f"{v1}\n{v2}" for v1, v2 in zip(group_counts,group_percentages)]
  labels = np.asarray(labels).reshape(len(labels_names),len(labels_names))
  sns.heatmap(cf_matrix, annot=labels, fmt='', cmap='Reds',xticklabels=labels_names,yticklabels=labels_names)
  plt.xlabel('Predykcja')
  plt.ylabel('Rzeczywistość')
  plt.show()

def print_heatmap(list_of_models: List[BaseEstimator], list_of_X_test: List[pd.DataFrame], y_test: List[pd.DataFrame], type_of_heatmap: str) -> None:
  '''
  The function displays a heat map for the indicated model list. On the map you can display: accuracy, recall, precision, F1.
  '''
  types_available = {'Accuracy', 'Recall', 'Precision', 'F1'}
  if type_of_heatmap not in types_available:
        raise ValueError("results: status must be one of %r." % types_available)
  list_of_values = []
  for i in range(12):
    temp = []
    for j in range(12):
      y_pred = list_of_models[i].predict(list_of_X_test[j])
      if type_of_heatmap == 'Accuracy':
        temp.append(accuracy_score(y_test, y_pred) *100)
      elif type_of_heatmap == 'Recall':
        temp.append(recall_score(y_test, y_pred) *100)
      elif type_of_heatmap == 'Precision':
        temp.append(precision_score(y_test, y_pred) *100)
      elif type_of_heatmap == 'F1':
        temp.append(f1_score(y_test, y_pred) *100)
    list_of_values.append(temp)
  miesiace = ['STY', 'LUT', 'MAR', 'KWI', 'MAJ', 'CZE', 'LIP', 'SIE', 'WRZ', 'PAZ', 'LIS', 'GRU']
  df = pd.DataFrame(list_of_values, index=miesiace, columns=miesiace)
  plt.figure(figsize=(10,8))
  sns.heatmap(df, annot=True)
  plt.xlabel('Miesiace - test')
  plt.ylabel('Miesiace - model')
  plt.title(type_of_heatmap)

class BalanceDataSet():
  '''
  Two techniques for handling imbalanced data.
  '''
  def __init__(
      self,
      X: pd.DataFrame,
      y: pd.DataFrame,
      random_seed: int = 2023
      ) -> None:
      self.X = X
      self.y = y
      assert len(self.X)==len(self.y)
      self.random_seed = random_seed
      self.oversample = RandomOverSampler(sampling_strategy='auto', random_state=random_seed)
      self.smote = SMOTE(random_state=random_seed)

  def useOverSampling(
      self,
      ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    return self.oversample.fit_resample(self.X, self.y)

  def useSMOTE(
      self,
      ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    return self.smote.fit_resample(self.X, self.y)

def plot_data_dist(y: pd.DataFrame) -> None:
  '''
  The function displays the distribution of data in the sample.
  '''
  dane = pd.Series(y).value_counts().sort_index()
  labels = list(np.sort(pd.unique(y)))
  ypos=np.arange(len(labels))
  plt.xticks(ypos, labels)
  plt.xlabel('Klasa')
  plt.ylabel('Czestosc')
  plt.title('Liczebnosc dla proby')
  plt.bar(ypos,dane)

def get_colormap(values: list, colors_palette: list, name = 'custom'):
    """
    Funkcja jako argumenty bierze liste wartosci okreslajacych granice przedzialow liczbowych, ktore
    beda okreslac jak dla rozwazanego parametru maja zmieniac się kolory punktow, ktorych lista stanowi
    drugi argument funkcji.
    """
    values = np.sort(np.array(values))
    values = np.interp(values, (values.min(), values.max()), (0, 1))
    cmap = mpl_colors.LinearSegmentedColormap.from_list(name, list(zip(values, colors_palette)))
    return cmap

def plot_map(df: pd.DataFrame, parameter_name: str, colormap: mpl_colors.LinearSegmentedColormap, title: str,
             point_size: int = 8, width: int = 800, height: int = 500, alpha: float = 1,
             bgcolor: str = 'white', colorbar_verbose: bool = True):

    gdf = gv.Points(df, ['lon', 'lat'], [parameter_name]) # obiekt zawierający punkty
    tiles = gts.OSM # wybór mapy tła, w tym wypadku OpenStreetMap

    # łączenie mapy tła z punktami i ustawienie wybranych parametrów wizualizacji
    map_with_points = tiles * gdf.opts(
        title=title,
        color=parameter_name,
        cmap=colormap,
        size=point_size,
        width=width,
        height=height,
        colorbar=colorbar_verbose,
        toolbar='above',
        tools=['hover', 'wheel_zoom', 'reset'],
        alpha=alpha, # przezroczystość
        bgcolor=bgcolor
    )
    return hv.render(map_with_points)

def plot_map_from_model(model: BaseEstimator, df: pd.DataFrame, title:Optional[str]='', col:int = 2) -> None:
  '''
  The function displays a map for the indicated model.
  '''
  assert col in {1,2,3}
  df['Model'] = model.predict(df.loc[:,'Rainf':'SoilM_100_200cm'])
  if col == 1:
    colormap_cluster=dict(zip(['1','2', '3'], ['yellow','#99B300', 'green']))
  elif col == 3:
    colormap_cluster=dict(zip(['1','0'], ['#99B300', 'green']))
  else:
    colormap_cluster=dict(zip(['1','0'], ['yellow', 'green']))
  plot = plot_map(df=df, parameter_name='Model', colormap=colormap_cluster, title=title, alpha=1)
  output_notebook()
  show(plot)

"""### Model 1 - detekcja pustynia - step - inne

#### Podzial na zbior treningowy i testowy
"""

number_of_data = len(list_of_df)

list_of_df_m1 = []

for i in range(number_of_data):
  list_of_df_m1.append(train_test_split(list_of_df[i], y_m1, test_size=0.2, random_state=2024))

list_of_df_m1_tr = [[i[0],i[2]] for i in list_of_df_m1]

list_of_df_m1_te = [[i[1],i[3]] for i in list_of_df_m1]

"""#### Zbalansowanie datasetow

Graficzne przedstawienie liczebnosci kazdej z klas w zbiorze testowym.
"""

plot_data_dist(list_of_df_m1_tr[0][1])

"""Balansujemy kazdy ze zbiorow."""

for i in range(number_of_data):
  list_of_df_m1_tr[i][0], list_of_df_m1_tr[i][1] = BalanceDataSet(list_of_df_m1_tr[i][0], list_of_df_m1_tr[i][1]).useSMOTE()

"""Przykladowe dane po zbalansowaniu."""

plot_data_dist(list_of_df_m1_tr[0][1])

"""#### Drzewa decyzyjne

Zdefiniujmy slownik paramentow drzewa ktory bedzie wykorzystany w metodzie GridSearchCV.
"""

params_gs_m1 = {'criterion': ('entropy', 'gini'),
            'max_depth': np.arange(6,15),
            'min_samples_split': np.arange(6,14),
            'min_samples_leaf': np.arange(3,8)}

"""Utworzenie listy modeli.


"""

list_of_models_m1, list_params_m1 = create_models(params_gs_m1, list_of_df_m1_tr)

"""### Model 2 - detekcja pustynia - niepustynia

#### Podzial na zbior treningowy i testowy
"""

list_of_df_m2 = []

for i in range(number_of_data):
  list_of_df_m2.append(train_test_split(list_of_df[i], y_m2, test_size=0.2, random_state=2024))

list_of_df_m2_tr = [[i[0],i[2]] for i in list_of_df_m2]

list_of_df_m2_te = [[i[1],i[3]] for i in list_of_df_m2]

"""#### Zbalansowanie datasetow

Graficzne przedstawienie liczebnosci kazdej z klas w zbiorze testowym.
"""

plot_data_dist(list_of_df_m2_tr[0][1])

"""Balansujemy kazdy ze zbiorow."""

for i in range(number_of_data):
  list_of_df_m2_tr[i][0], list_of_df_m2_tr[i][1] = BalanceDataSet(list_of_df_m2_tr[i][0], list_of_df_m2_tr[i][1]).useSMOTE()

"""Przykladowe dane po zbalansowaniu."""

plot_data_dist(list_of_df_m2_tr[0][1])

"""#### Drzewa decyzyjne

Zdefiniujmy slownik paramentow drzewa ktory bedzie wykorzystany w metodzie GridSearchCV.
"""

params_gs_m2 = {'criterion': ('entropy', 'gini'),
            'max_depth': np.arange(6,15),
            'min_samples_split': np.arange(7,16),
            'min_samples_leaf': np.arange(4,11)}

"""Utworzenie listy modeli."""

list_of_models_m2, list_params_m2 = create_models(params_gs_m2, list_of_df_m2_tr, 'accuracy')

"""### Model 3 - detekcja step - niestep

#### Podzial na zbior treningowy i testowy
"""

list_of_df_m3 = []

for i in range(number_of_data):
  list_of_df_m3.append(train_test_split(list_of_df[i], y_m3, test_size=0.2, random_state=2024))

list_of_df_m3_tr = [[i[0],i[2]] for i in list_of_df_m3]

list_of_df_m3_te = [[i[1],i[3]] for i in list_of_df_m3]

"""#### Zbalansowanie datasetow

Graficzne przedstawienie liczebnosci kazdej z klas w zbiorze testowym.
"""

plot_data_dist(list_of_df_m3_tr[0][1])

"""Balansujemy kazdy ze zbiorow."""

for i in range(number_of_data):
  list_of_df_m3_tr[i][0], list_of_df_m3_tr[i][1] = BalanceDataSet(list_of_df_m3_tr[i][0], list_of_df_m3_tr[i][1]).useSMOTE()

"""Przykladowe dane po zbalansowaniu."""

plot_data_dist(list_of_df_m3_tr[0][1])

"""#### Drzewa decyzyjne

Zdefiniujmy slownik paramentow drzewa ktory bedzie wykorzystany w metodzie GridSearchCV.
"""

params_gs_m3 = {'criterion': ('entropy', 'gini'),
            'max_depth': np.arange(6,14),
            'min_samples_split': np.arange(10,14),
            'min_samples_leaf':np.arange(4,10)}

"""Utworzenie listy modeli."""

list_of_models_m3, list_params_m3 = create_models(params_gs_m3, list_of_df_m3_tr, 'accuracy')

"""### Ocena modeli

W tym rozdziale zostana przedstawione mapy ciepla obrazujace wartosci roznych statystyk dla modeli. Wiersze oznaczaja dane miesieczne na ktorych zostal zbudowany model, kolumny dane na ktorych byl testowany.

 Dla kazdego rodzaju modeli, zostanie wybrany najlepszy klasyfikator i dodatkowo sprawdzony.

#### Model 1 - detekcja pustynia - step - inne

Accuracy na zbiorze treningowym.
"""

print_heatmap(list_of_models_m1, [i[0] for i in list_of_df_m1_tr], list_of_df_m1_tr[0][1], 'Accuracy')

"""Accuracy na zbiorze testowym."""

print_heatmap(list_of_models_m1, [i[0] for i in list_of_df_m1_te], list_of_df_m1_te[0][1], 'Accuracy')

"""##### Wnioski

Wnioskujemy, ze w znaczacej liczbie przypadkow zbudowanie modelu uzywajac danych dla miesiaca na ktorym jest testowany, przynosi najlepsze efekty. Sposrod zbudowanych modeli najlepszy wydaje sie ten zbudowany na danych czerwcowych, na zbiorze testowym jego wynik wynosi 84%.

**Podsumowanie dla zbudowanego modelu na danych czerwcowych.**

Zbior treningowy
"""

summary_model(list_of_models_m1[5], list_of_df_m1_tr[5][0], list_of_df_m1_tr[5][1], ['1','2','3'])
print(classification_report(list_of_df_m1_tr[5][1], list_of_models_m1[5].predict(list_of_df_m1_tr[5][0])))

"""Zbior testowy"""

summary_model(list_of_models_m1[5], list_of_df_m1_te[5][0], list_of_df_m1_te[5][1], ['1','2','3'])
print(classification_report(list_of_df_m1_te[5][1], list_of_models_m1[5].predict(list_of_df_m1_te[5][0])))

plot_map_from_model(list_of_models_m1[5], list_df_months[5], "Czerwiec - detekcja pustynia (1) - step(2) - inne(3)", 1)

"""Porownujac otrzymana mape z danymi o strukturamch pustyn w Ameryce zauwazamy, ze model nie rozpoznaje zimnych pustyn na granicy USA i Kanady. Klasyfikator myli sie rowniez w okolicy Bahamow - uznaje je za pustynie.

#### Model 2 - detekcja pustynia - niepustynia

Accuracy na zbiorze treningowym.
"""

print_heatmap(list_of_models_m2, [i[0] for i in list_of_df_m2_tr], list_of_df_m2_tr[0][1], 'Accuracy')

"""Accuracy na zbiorze testowym."""

print_heatmap(list_of_models_m2, [i[0] for i in list_of_df_m2_te], list_of_df_m2_te[0][1], 'Accuracy')

"""Recall na zbiorze testowym."""

print_heatmap(list_of_models_m2, [i[0] for i in list_of_df_m2_te], list_of_df_m2_te[0][1], 'Recall')

"""Precision na zbiorze testowym."""

print_heatmap(list_of_models_m2, [i[0] for i in list_of_df_m2_te], list_of_df_m2_te[0][1], 'Precision')

"""F1 na zbiorze testowym."""

print_heatmap(list_of_models_m2, [i[0] for i in list_of_df_m2_te], list_of_df_m2_te[0][1], 'F1')

"""##### Wnioski

Najlepszy wynik klasyfikacji osiagamy na danych z sierpnia. Accuarcy na zbiorze testowym wynosi wowczas 90%.

**Podsumowanie dla zbudowanego modelu na danych serpniowych.**

Zbior treningowy
"""

summary_model(list_of_models_m2[7], list_of_df_m2_tr[7][0], list_of_df_m2_tr[7][1], ['0','1'])
print(classification_report(list_of_df_m2_tr[7][1], list_of_models_m2[7].predict(list_of_df_m2_tr[7][0])))

"""Zbior testowy"""

summary_model(list_of_models_m2[7], list_of_df_m2_te[7][0], list_of_df_m2_te[7][1], ['0','1'])
print(classification_report(list_of_df_m2_te[7][1], list_of_models_m2[7].predict(list_of_df_m2_te[7][0])))

plot_map_from_model(list_of_models_m2[7], list_df_months[7], "Sierpien - detekcja pustynia (1) - niepustynia (0)", 2)

"""Porownujac otrzymana mape z danymi o strukturamch pustyn w Ameryce zauwazamy, ze model nie rozpoznaje jednej z zimnowych pustyn na granicy USA i Kanady. Klasyfikator myli sie podobnie w okolicy Bahamow - uznaje je za pustynie oraz nad Zatoka Meksykanska.

#### Model 3 - detekcja step - niestep

Accuracy na zbiorze treningowym.
"""

print_heatmap(list_of_models_m3, [i[0] for i in list_of_df_m3_tr], list_of_df_m3_tr[0][1], 'Accuracy')

"""Accuracy na zbiorze testowym."""

print_heatmap(list_of_models_m3, [i[0] for i in list_of_df_m3_te], list_of_df_m3_te[0][1], 'Accuracy')

"""Recall na zbiorze testowym."""

print_heatmap(list_of_models_m3, [i[0] for i in list_of_df_m3_te], list_of_df_m3_te[0][1], 'Recall')

"""Precision na zbiorze testowym."""

print_heatmap(list_of_models_m3, [i[0] for i in list_of_df_m3_te], list_of_df_m3_te[0][1], 'Precision')

"""F1 na zbiorze testowym."""

print_heatmap(list_of_models_m3, [i[0] for i in list_of_df_m3_te], list_of_df_m3_te[0][1], 'F1')

"""##### Wnioski

Najlepszy wynik klasyfikacji osiagamy na danych z czerwca. Accuarcy na zbiorze testowym wynosi wowczas 85%. Jak zobaczymy na kolejnej mapie, klasyfikator uznaje czesc pustyn za stepy.

**Podsumowanie dla zbudowanego modelu na danych czerwcowych.**

Zbior treningowy
"""

summary_model(list_of_models_m3[5], list_of_df_m3_tr[5][0], list_of_df_m3_tr[5][1], ['0','1'])
print(classification_report(list_of_df_m3_tr[5][1], list_of_models_m3[5].predict(list_of_df_m3_tr[5][0])))

"""Zbior testowy"""

summary_model(list_of_models_m3[5], list_of_df_m3_te[5][0], list_of_df_m3_te[5][1], ['0','1'])
print(classification_report(list_of_df_m3_te[5][1], list_of_models_m3[5].predict(list_of_df_m3_te[5][0])))

plot_map_from_model(list_of_models_m3[5], list_df_months[5],"Czerwiec - detekcja step (1) - niestep (0)", 3)

"""Klasyfikacja mozna uznać za poprawna, niektore putynie uznane sa za stepy. Problemem sa małe, rozproszone obszary wschodniej czesci kontynentu, w innych zrodlach nie ma tam stepow.

### Zapisanie modeli
"""

models_path = '/content/drive/MyDrive/BigMess/NASA/Modele/Klasyfikacja/'

for month in range(12):
  #Model 1
  with open(models_path+f'Model_m1/{month+1:02d}', 'wb') as files:
    pickle.dump(list_of_models_m1[i], files)
  #Model 2
  with open(models_path+f'Model_m2/{month+1:02d}', 'wb') as files:
    pickle.dump(list_of_models_m2[i], files)
  #Model 3
  with open(models_path+f'Model_m3/{month+1:02d}', 'wb') as files:
    pickle.dump(list_of_models_m3[i], files)

"""## Przedstawienie wynikow na mapach"""

display(IFrame("https://www.google.com/maps/embed?pb=!1m14!1m12!1m3!1d13982681.959428234!2d-98.66341902257437!3d38.39997874427714!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!5e1!3m2!1spl!2spl!4v1703000232420!5m2!1spl!2spl", '800px', '500px'))

"""### Dane z 07.2023

Do klasyfikacji wykorzytamy modele zbudowane na danych lipcowych. Dane z tego miesiaca byly uznane przez zespol za najlepsze do identyfikacji terenow pustynnych.
"""

plot_map_from_model(list_of_models_m1[6], list_df_months[6], "Detekcja pustynia (1) - step(2) - inne(3)",1)

plot_map_from_model(list_of_models_m2[6], list_df_months[6], "Detekcja pustynia (1) - niepustynia (0)",2)

plot_map_from_model(list_of_models_m3[6], list_df_months[6],"Detekcja step (1) - niestep (0)", 3)

"""### Dane z 06.2023

Do klasyfikacji wykorzystamy modele zbudowane na danych listopadowych. Eksperyment ma na celu przetestowania klasyfikatorow na danych innych niz miesiac ich budowy.
"""

plot_map_from_model(list_of_models_m1[10], list_df_months[5], "Detekcja pustynia (1) - step(2) - inne(3)",1)

plot_map_from_model(list_of_models_m2[10], list_df_months[5], "Detekcja pustynia (1) - niepustynia (0)", 2)

plot_map_from_model(list_of_models_m3[10], list_df_months[5],"Detekcja step (1) - niestep (0)",3)

"""### Klasyfikacja pustynia-step-inne dla kazdego miesiaca"""

miesiace = ['Styczen - ', 'Luty - ', 'Marzec - ', 'Kwiecien - ', 'Maj - ', 'Czerwiec - ', 'Lipiec - ', 'Sierpien - ', 'Wrzesien - ', 'Pazdziernik - ', 'Listopad - ', 'Grudzien - ']
for i in range(12):
  plot_map_from_model(list_of_models_m1[i], list_df_months[i], miesiace[i]+"detekcja pustynia (1) - step(2) - inne(3)",1)

"""### Klasyfikacja pustyn dla kazdego miesiaca"""

for i in range(12):
  plot_map_from_model(list_of_models_m2[i], list_df_months[i], miesiace[i]+"detekcja pustynia (1) - niepustynia (0)",2)

"""## Lasy losowe

**Metoda**:

Do modelowania uzyto metody lasow losowych oraz wykorzystano te miesiace ktore okazaly sie najlepsze w modelach drzew decyzyjnych.

Zdefiniujmy slownik paramentow modelu ktory bedzie wykorzystany w metodzie GridSearchCV.
"""

params_gs_las = {'n_estimators': [10,20,30,40,50,60,70,80,90,100,110],
                  'max_depth': np.arange(7,11),
                  'min_samples_leaf': np.arange(4,8)}

"""### Model 1 - detekcja pustynia - step - inne

Model zostanie zbudowany na danych z czerwca.
"""

gs_las_m1 = GridSearchCV(RandomForestClassifier(random_state = 2024), cv = 5, param_grid = params_gs_las, scoring = 'accuracy')
gs_las_m1.fit(list_of_df_m1_tr[5][0], list_of_df_m1_tr[5][1])

las_m1 = RandomForestClassifier(random_state = 2024, **gs_las_m1.best_params_)

las_m1.fit(list_of_df_m1_tr[5][0], list_of_df_m1_tr[5][1])

"""Zbior treningowy"""

summary_model(las_m1, list_of_df_m1_tr[5][0], list_of_df_m1_tr[5][1], ['1','2','3'])
print(classification_report(list_of_df_m1_tr[5][1], las_m1.predict(list_of_df_m1_tr[5][0])))

"""Zbior testowy"""

summary_model(las_m1, list_of_df_m1_te[5][0], list_of_df_m1_te[5][1], ['1','2','3'])
print(classification_report(list_of_df_m1_te[5][1], las_m1.predict(list_of_df_m1_te[5][0])))

plot_map_from_model(las_m1, list_df_months[5], "Czerwiec - detekcja pustynia (1) - step(2) - inne(3)", 1)

"""Model o wynikach podobnych do modelu drzew decyzyjnych.

### Model 2 - detekcja pustynia - niepustynia

Model zostanie zbudowany na danych z lipca oraz sierpnia. Dla sierpnia byly najlepsze wyniki w drzewach, lipiec byl drugi.

**Sierpien**
"""

gs_las_m2 = GridSearchCV(RandomForestClassifier(random_state = 2024), cv = 5, param_grid = params_gs_las, scoring = 'accuracy')
gs_las_m2.fit(list_of_df_m2_tr[7][0], list_of_df_m2_tr[7][1])

las_m2 = RandomForestClassifier(random_state = 2024, **gs_las_m2.best_params_)

las_m2.fit(list_of_df_m2_tr[7][0], list_of_df_m2_tr[7][1])

"""Zbior treningowy"""

summary_model(las_m2, list_of_df_m2_tr[7][0], list_of_df_m2_tr[7][1], ['0','1'])
print(classification_report(list_of_df_m2_tr[7][1], las_m2.predict(list_of_df_m2_tr[7][0])))

"""Zbior testowy"""

summary_model(las_m2, list_of_df_m2_te[7][0], list_of_df_m2_te[7][1], ['0','1'])
print(classification_report(list_of_df_m2_te[7][1], las_m2.predict(list_of_df_m2_te[7][0])))

plot_map_from_model(las_m2, list_df_months[7], "Sierpien - detekcja pustynia (1) - niepustynia (0)", 2)

"""**Lipiec**"""

gs_las_m2_7 = GridSearchCV(RandomForestClassifier(random_state = 2024), cv = 5, param_grid = params_gs_las, scoring = 'accuracy')
gs_las_m2_7.fit(list_of_df_m2_tr[6][0], list_of_df_m2_tr[6][1])

gs_las_m2_7.best_params_

las_m2_7 = RandomForestClassifier(random_state = 2024, **gs_las_m2_7.best_params_)

las_m2_7.fit(list_of_df_m2_tr[6][0], list_of_df_m2_tr[6][1])

"""Zbior treningowy"""

summary_model(las_m2_7, list_of_df_m2_tr[6][0], list_of_df_m2_tr[6][1], ['0','1'])
print(classification_report(list_of_df_m2_tr[6][1], las_m2_7.predict(list_of_df_m2_tr[6][0])))

"""Zbior testowy"""

summary_model(las_m2_7, list_of_df_m2_te[6][0], list_of_df_m2_te[6][1], ['0','1'])
print(classification_report(list_of_df_m2_te[6][1], las_m2_7.predict(list_of_df_m2_te[6][0])))

plot_map_from_model(las_m2_7, list_df_months[6], "Lipiec - detekcja pustynia (1) - niepustynia (0)")

"""Lepsze wyniki otrzymano dla danych z lipca. Model osiągnal 92% accuracy, 89% recall oraz 57% precision. Klasyfikator lasow losowych zbudowany na tych danych wydaje sie być jednym z lepszych. Widac sklasyfikowane zimne pustynie na granicy USA i Kandy. Nieprawidlowo sklasyfikowano obszary nad Zatoka Meksykanska.

### Model 3 - detekcja step - niestep

Model zostanie zbudowany na danych z czerwca.
"""

gs_las_m3 = GridSearchCV(RandomForestClassifier(random_state = 2024), cv = 5, param_grid = params_gs_las, scoring = 'accuracy')
gs_las_m3.fit(list_of_df_m3_tr[5][0], list_of_df_m3_tr[5][1])

las_m3 = RandomForestClassifier(random_state = 2024, **gs_las_m3.best_params_)

las_m3.fit(list_of_df_m3_tr[5][0], list_of_df_m3_tr[5][1])

"""Zbior treningowy"""

summary_model(las_m3, list_of_df_m3_tr[5][0], list_of_df_m3_tr[5][1], ['0','1'])
print(classification_report(list_of_df_m3_tr[5][1], las_m3.predict(list_of_df_m3_tr[5][0])))

"""Zbior testowy"""

summary_model(las_m3, list_of_df_m3_te[5][0], list_of_df_m3_te[5][1], ['0','1'])
print(classification_report(list_of_df_m3_te[5][1], las_m3.predict(list_of_df_m3_te[5][0])))

plot_map_from_model(las_m3, list_df_months[5], "Czerwiec - detekcja step (1) - niestep (0)", 3)

"""Model nieznacznie lepszy od modelu drzew decyzyjnych zbudowanego na tym samym miesiacu. Udalo sie zdecydowanie ograniczyc liczbe obszarow uznanych za stepy w wschodniej czesci kontynentu.

### Zapisanie modeli
"""

with open(models_path+'Lasy/las_m1', 'wb') as files:
  pickle.dump(las_m1, files)

with open(models_path+'Lasy/las_m2', 'wb') as files:
  pickle.dump(las_m2, files)

with open(models_path+'Lasy/las_m2_7', 'wb') as files:
  pickle.dump(las_m2_7, files)

with open(models_path+'Lasy/las_m3', 'wb') as files:
  pickle.dump(las_m3, files)

"""## Light GBM

**Metoda**:

Do modelowania uzyto metody LightGBM oraz wykorzystano te miesiace ktore okazaly sie najlepsze w modelach drzew decyzyjnych.

Zdefiniujmy slownik paramentow modelu ktory bedzie wykorzystany w metodzie GridSearchCV.
"""

params_gs_lgbm = {'n_estimators':  [10,50,100,120],
                  'num_leaves': [10,20,30,40],
                  'max_depth': np.arange(5,11)}

"""### Model 1 - detekcja pustynia - step - inne

Model zostanie zbudowany na danych z czerwca.
"""

gs_lgbm_m1 = GridSearchCV(LGBMClassifier(random_state = 2024), cv = 5, param_grid = params_gs_lgbm, scoring = 'accuracy')
gs_lgbm_m1.fit(list_of_df_m1_tr[5][0], list_of_df_m1_tr[5][1])

lgbm_m1 = LGBMClassifier(random_state = 2024,**gs_lgbm_m1.best_params_)

lgbm_m1.fit(list_of_df_m1_tr[5][0], list_of_df_m1_tr[5][1])

"""Zbior treningowy"""

summary_model(lgbm_m1, list_of_df_m1_tr[5][0], list_of_df_m1_tr[5][1], ['1','2','3'])
print(classification_report(list_of_df_m1_tr[5][1], lgbm_m1.predict(list_of_df_m1_tr[5][0])))

"""Zbior testowy"""

summary_model(lgbm_m1, list_of_df_m1_te[5][0], list_of_df_m1_te[5][1], ['1','2','3'])
print(classification_report(list_of_df_m1_te[5][1], lgbm_m1.predict(list_of_df_m1_te[5][0])))

plot_map_from_model(lgbm_m1, list_df_months[5], "Czerwiec - detekcja pustynia (1) - step(2) - inne(3)",1)

"""Model o wynikach podobnych do modelu drzew decyzyjnych i lasow losowych. Widac ograniczenie w klasyfikacji pustyn w okolocy Bahamow.

### Model 2 - detekcja pustynia - niepustynia

Model zostanie zbudowany na danych z lipca oraz sierpnia. Dla sierpnia byly najlepsze wyniki w drzewach, lipiec byl drugi.

**Sierpien**
"""

gs_lgbm_m2 = GridSearchCV(LGBMClassifier(random_state = 2024), cv = 5, param_grid = params_gs_lgbm, scoring = 'accuracy')
gs_lgbm_m2.fit(list_of_df_m2_tr[7][0], list_of_df_m2_tr[7][1])

lgbm_m2 = LGBMClassifier(random_state = 2024, **gs_lgbm_m2.best_params_)

lgbm_m2.fit(list_of_df_m2_tr[7][0], list_of_df_m2_tr[7][1])

"""Zbior treningowy"""

summary_model(lgbm_m2, list_of_df_m2_tr[7][0], list_of_df_m2_tr[7][1], ['0','1'])
print(classification_report(list_of_df_m2_tr[7][1], lgbm_m2.predict(list_of_df_m2_tr[7][0])))

"""Zbior testowy"""

summary_model(lgbm_m2, list_of_df_m2_te[7][0], list_of_df_m2_te[7][1], ['0','1'])
print(classification_report(list_of_df_m2_te[7][1], lgbm_m2.predict(list_of_df_m2_te[7][0])))

plot_map_from_model(lgbm_m2, list_df_months[7], "Sierpien - detekcja pustynia (1) - niepustynia (0)", 2)

"""**Lipiec**"""

gs_lgbm_m2_7 = GridSearchCV(LGBMClassifier(random_state = 2024), cv = 5, param_grid = params_gs_lgbm, scoring = 'accuracy')
gs_lgbm_m2_7.fit(list_of_df_m2_tr[6][0], list_of_df_m2_tr[6][1])

lgbm_m2_7 = LGBMClassifier(random_state = 2024, **gs_lgbm_m2_7.best_params_)

lgbm_m2_7.fit(list_of_df_m2_tr[6][0], list_of_df_m2_tr[6][1])

gs_lgbm_m2_7.best_params_

"""Zbior treningowy"""

summary_model(lgbm_m2_7, list_of_df_m2_tr[6][0], list_of_df_m2_tr[6][1], ['0','1'])
print(classification_report(list_of_df_m2_tr[6][1], lgbm_m2_7.predict(list_of_df_m2_tr[6][0])))

"""Zbior testowy"""

summary_model(lgbm_m2_7, list_of_df_m2_te[6][0], list_of_df_m2_te[6][1], ['0','1'])
print(classification_report(list_of_df_m2_te[6][1], lgbm_m2_7.predict(list_of_df_m2_te[6][0])))

plot_map_from_model(lgbm_m2_7, list_df_months[6], "Lipiec - detekcja pustynia (1) - niepustynia (0)", 2)

"""Lepsze wyniki otrzymano dla danych z lipca. W porownaniu do modeli drzew i lasow ten kalsyfikator dziala lepiej w rejonie Zatoki Meksykanskiej, jednak minimalnie gorzej klasyfikuje pustynie zimne.

### Model 3 - detekcja step - niestep

Model zostanie zbudowany na danych z czerwca.
"""

gs_lgbm_m3 = GridSearchCV(LGBMClassifier(random_state = 2024), cv = 5, param_grid = params_gs_lgbm, scoring = 'accuracy')
gs_lgbm_m3.fit(list_of_df_m3_tr[5][0], list_of_df_m3_tr[5][1])

lgbm_m3 = LGBMClassifier(random_state = 2024, **gs_lgbm_m3.best_params_)

lgbm_m3.fit(list_of_df_m3_tr[5][0], list_of_df_m3_tr[5][1])

"""Zbior treningowy"""

summary_model(lgbm_m3, list_of_df_m3_tr[5][0], list_of_df_m3_tr[5][1], ['0','1'])
print(classification_report(list_of_df_m3_tr[5][1], lgbm_m3.predict(list_of_df_m3_tr[5][0])))

"""Zbior testowy"""

summary_model(lgbm_m3, list_of_df_m3_te[5][0], list_of_df_m3_te[5][1], ['0','1'])
print(classification_report(list_of_df_m3_te[5][1], lgbm_m3.predict(list_of_df_m3_te[5][0])))

plot_map_from_model(lgbm_m3, list_df_months[5], "Czerwiec - detekcja step (1) - niestep (0)", 3)

"""Model podobny jakosciowo to poprzednich klasyfikatorow step - niestep.

### Zapisanie modeli
"""

with open(models_path+'LightGBM/lgbm_m1', 'wb') as files:
  pickle.dump(lgbm_m1, files)

with open(models_path+'LightGBM/lgbm_m2', 'wb') as files:
  pickle.dump(lgbm_m2, files)

with open(models_path+'LightGBM/lgbm_m2_7', 'wb') as files:
  pickle.dump(lgbm_m2_7, files)

with open(models_path+'LightGBM/lgbm_m3', 'wb') as files:
  pickle.dump(lgbm_m3, files)

"""## Uwzglednienie wartosci *lat* w modelu pustynia - niepustynia

W klasyfikacji pustynia - nie pustynia problematyczne wydaje sie klasyfikowanie zimnych pustyn wysunietych najbardziej na polnoc oraz bledna klasyfikacja obszarow nad Zatoka Meksykanska jako pustynie. Cecha majaca wplyw na polepszenie modelu przypuszczalnie moze byc kontekst geograficzny. W tym rozdziale podjeto probe rozszerzenia cech w modelu o *lat* czyli szerokosc geograficzna.

Na danych z lipca zbudujemy dwa modele: lasow losowych i LifhtGBM.

**Przygotowanie danych**
"""

july_an = list_of_df_all[6].loc[:,'lat':'SoilM_100_200cm']

july_X_tr, july_X_te, july_y_tr, july_y_te = train_test_split(july_an, y_m2, test_size=0.2, random_state=2024)

"""### Lasy losowe

Do strojenia hiperparametrow zostal uzyty ten sam zestaw cech jak w rozdziale o lasach losowych.
"""

gs_las_lat = GridSearchCV(RandomForestClassifier(random_state = 2024), cv = 5, param_grid = params_gs_las, scoring = 'accuracy')
gs_las_lat.fit(july_X_tr, july_y_tr)

las_m2_lat = RandomForestClassifier(random_state = 2024, **gs_las_lat.best_params_)

las_m2_lat.fit(july_X_tr, july_y_tr)

"""Zbior treningowy"""

summary_model(las_m2_lat, july_X_tr, july_y_tr, ['0','1'])
print(classification_report(july_y_tr, las_m2_lat.predict(july_X_tr)))

"""Zbior testowy"""

summary_model(las_m2_lat, july_X_te, july_y_te, ['0','1'])
print(classification_report(july_y_te, las_m2_lat.predict(july_X_te)))

df_july = list_df_months[6]
df_july['las_m2_lat'] = las_m2_lat.predict(df_july.loc[:,'lat':'SoilM_100_200cm'])
colormap_cluster=dict(zip(['1','0'], ['yellow', 'green']))
plot_las_july = plot_map(df=df_july, parameter_name='las_m2_lat', colormap=colormap_cluster, title="Lipiec - detekcja pustynia (1) - niepustynia (0)", alpha=1)
output_notebook()
show(plot_las_july)

"""Model ma lepsze precision 66% (wieksze o 9 p.p. od modelu drzew bez *lat*) oraz gorsze recall 70% (mniejsze o 19% p.p. od modelu drzew bez *lat*). Interpretujac powyzsza mape widzimy, ze ten model nie ma problemu z obszarami nad Zatoka Meksykanska. Zmniejszyla sie natomiast poprawnosc klasyfikacji zimnych pustyn.

### Light GBM

Do strojenia hiperparametrow zostal uzyty ten sam zestaw cech jak w rozdziale o modelach Light GBM.
"""

gs_lgbm_lat = GridSearchCV(LGBMClassifier(random_state = 2024), cv = 5, param_grid = params_gs_lgbm, scoring = 'accuracy')
gs_lgbm_lat.fit(july_X_tr, july_y_tr)

lgbm_m2_lat = LGBMClassifier(random_state = 2024, **gs_lgbm_lat.best_params_)

lgbm_m2_lat.fit(july_X_tr, july_y_tr)

"""Zbior treningowy"""

summary_model(lgbm_m2_lat, july_X_tr, july_y_tr, ['0','1'])
print(classification_report(july_y_tr, lgbm_m2_lat.predict(july_X_tr)))

"""Zbior testowy"""

summary_model(lgbm_m2_lat, july_X_te, july_y_te, ['0','1'])
print(classification_report(july_y_te, lgbm_m2_lat.predict(july_X_te)))

df_july['lgbm_m2_lat'] = lgbm_m2_lat.predict(df_july.loc[:,'lat':'SoilM_100_200cm'])
colormap_cluster=dict(zip(['1','0'], ['yellow', 'green']))
plot_lgbm_july = plot_map(df=df_july, parameter_name='lgbm_m2_lat', colormap=colormap_cluster, title="Lipiec - detekcja pustynia (1) - niepustynia (0)", alpha=1)
output_notebook()
show(plot_lgbm_july)

"""Model nieznacznie gorszy od modelu Light GBM bez cechy *lat*. Zmniejszyl sie problem klasyfikacji obszarow przy Zatoce Meksykanskiej, pogłebil problem zimnych pustyn.

### Zapisanie modeli
"""

with open(models_path+'Modele_z_lat/las_m2_lat', 'wb') as files:
  pickle.dump(las_m2_lat, files)

with open(models_path+'Modele_z_lat/lgbm_m2_lat', 'wb') as files:
  pickle.dump(lgbm_m2_lat, files)

"""## Podsumowanie

W ramach zadania zostało zbudowanychy 18 modeli klasyfikacji pustynia - niepustynia. Najlepsze wydaja sie modele:

* Lasów losowych na danych lipcowych - [sciezka do pliku]('/content/drive/MyDrive/BigMess/NASA/Modele/Klasyfikacja/Lasy/las_m2_7')
* Light GBM na danych lipcowych - [sciezka do pliku]('/content/drive/MyDrive/BigMess/NASA/Modele/Klasyfikacja/LightGBM/lgbm_m2_7')
* Lasów losowcych z cehcą *lat* na danych lipcowych- [sciezka do pliku]('/content/drive/MyDrive/BigMess/NASA/Modele/Klasyfikacja/Modele_z_lat/las_m2_lat')

dla tych modeli accuracy wacha się w okolicach 91%, a wartosc statystyki F1 w granicach 70%.

Dla klasyfikacji pustynia - step - inne najlepszy model to las losowy na danych czerwcowych - [sciezka do pliku]('/content/drive/MyDrive/BigMess/NASA/Modele/Klasyfikacja/Lasy/las_m1')

Dla klasyfikacji step - niestep najlepszy model to Light GLM na danych czerwcowych - [sciezka do pliku](/content/drive/MyDrive/BigMess/NASA/Modele/Klasyfikacja/LightGBM/lgbm_m3)
"""