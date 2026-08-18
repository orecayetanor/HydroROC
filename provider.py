from qgis.PyQt.QtGui import QIcon
import os
from qgis.core import QgsProcessingProvider
from .algorithms.delimitacion_automatica import DelimitarCuencaRios
from .algorithms.parametros_i import ParametrosCuencaCompleto
from .algorithms.parametros_ii import ParametrosRedDrenajeCompleto


class HydroROCProvider(QgsProcessingProvider):
    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon.png'))

    def loadAlgorithms(self):
        self.addAlgorithm(DelimitarCuencaRios())
        self.addAlgorithm(ParametrosCuencaCompleto())
        self.addAlgorithm(ParametrosRedDrenajeCompleto())

    def id(self):
        return 'hydroroc'

    def name(self):
        return 'HydroROC'

    def longName(self):
        return 'HydroROC - Herramientas Hidrológicas'
