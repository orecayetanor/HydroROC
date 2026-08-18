from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsRaster
)

from qgis.PyQt.QtCore import QVariant

import processing
import math
import numpy as np


class ParametrosCuencaCompleto(QgsProcessingAlgorithm):

    CUENCA = 'CUENCA'
    DEM = 'DEM'

    SALIDA = 'SALIDA'
    EJE_AXIAL = 'EJE_AXIAL'
    PUNTOS_EJE = 'PUNTOS_EJE'
    CUENCA_PARAM = 'CUENCA_PARAM'

    # =========================================================
    # INTERFAZ
    # =========================================================

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CUENCA,
                'Cuenca delimitada',
                [QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.DEM,
                'DEM recortado'
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.SALIDA,
                'Punto de salida automático',
                QgsProcessing.TypeVectorPoint
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.EJE_AXIAL,
                'Eje axial',
                QgsProcessing.TypeVectorLine
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PUNTOS_EJE,
                'Puntos del eje axial',
                QgsProcessing.TypeVectorPoint
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.CUENCA_PARAM,
                'Cuenca con parámetros morfométricos',
                QgsProcessing.TypeVectorPolygon
            )
        )

    # =========================================================
    # FUNCIONES
    # =========================================================

    def distancia(self, p1, p2):

        return math.hypot(
            p2.x() - p1.x(),
            p2.y() - p1.y()
        )

    # ---------------------------------------------------------

    def valor_dem(self, dem, punto):

        resultado = dem.dataProvider().identify(
            punto,
            QgsRaster.IdentifyFormatValue
        )

        if not resultado.isValid():
            return None

        valores = resultado.results()

        if 1 not in valores:
            return None

        valor = valores[1]

        if valor is None:
            return None

        try:
            valor = float(valor)
        except:
            return None

        if math.isnan(valor):
            return None

        return valor

    # =========================================================
    # PROCESO
    # =========================================================

    def processAlgorithm(
        self,
        parameters,
        context,
        feedback
    ):

        feedback.pushInfo('')
        feedback.pushInfo(
            '====================================================='
        )
        feedback.pushInfo(
            'PARÁMETROS MORFOMÉTRICOS DE LA CUENCA'
        )
        feedback.pushInfo(
            'GEOMETRÍA - FORMA - RELIEVE'
        )
        feedback.pushInfo(
            '====================================================='
        )

        # =====================================================
        # 1. CUENCA
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '1. Leyendo cuenca...'
        )

        cuenca = self.parameterAsSource(
            parameters,
            self.CUENCA,
            context
        )

        if cuenca is None:

            raise QgsProcessingException(
                'No se pudo cargar la cuenca.'
            )

        crs = cuenca.sourceCrs()

        if not crs.isValid():

            raise QgsProcessingException(
                'CRS de cuenca no válido.'
            )

        if crs.isGeographic():

            raise QgsProcessingException(
                'La cuenca debe estar proyectada en metros.'
            )

        feedback.pushInfo(
            'CRS: {}'.format(crs.authid())
        )

        # -----------------------------------------------------
        # UNIR GEOMETRÍAS
        # -----------------------------------------------------

        geometrias = []

        for f in cuenca.getFeatures():

            if not f.hasGeometry():
                continue

            g = f.geometry()

            if g is None or g.isEmpty():
                continue

            geometrias.append(
                QgsGeometry(g)
            )

        if not geometrias:

            raise QgsProcessingException(
                'No existen geometrías válidas.'
            )

        if len(geometrias) == 1:

            geom_cuenca = geometrias[0]

        else:

            geom_cuenca = QgsGeometry.unaryUnion(
                geometrias
            )

        if not geom_cuenca.isGeosValid():

            geom_cuenca = geom_cuenca.makeValid()

        # =====================================================
        # 2. DEM
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '2. Leyendo DEM...'
        )

        dem = self.parameterAsRasterLayer(
            parameters,
            self.DEM,
            context
        )

        if dem is None:

            raise QgsProcessingException(
                'No se pudo cargar el DEM.'
            )

        if dem.crs() != crs:

            feedback.pushInfo(
                'ADVERTENCIA: DEM y cuenca tienen CRS diferentes.'
            )

        res_x = abs(
            dem.rasterUnitsPerPixelX()
        )

        res_y = abs(
            dem.rasterUnitsPerPixelY()
        )

        feedback.pushInfo(
            'Resolución DEM: {:.3f} x {:.3f} m'.format(
                res_x,
                res_y
            )
        )

        # =====================================================
        # 3. GEOMETRÍA
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '3. Calculando geometría...'
        )

        area_m2 = geom_cuenca.area()

        area_km2 = (
            area_m2 /
            1_000_000.0
        )

        perimetro_m = geom_cuenca.length()

        perimetro_km = (
            perimetro_m /
            1000.0
        )

        geom_cent = geom_cuenca.centroid()

        centroide = QgsPointXY(
            geom_cent.asPoint()
        )

        # =====================================================
        # 4. PUNTO DE SALIDA AUTOMÁTICO
        #
        # Se busca el vértice del límite con menor elevación.
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '4. Buscando punto de salida automático...'
        )

        salida = None
        cota_salida = float('inf')

        for v in geom_cuenca.vertices():

            p = QgsPointXY(
                v.x(),
                v.y()
            )

            z = self.valor_dem(
                dem,
                p
            )

            if z is None:
                continue

            if z < cota_salida:

                cota_salida = z
                salida = p

        if salida is None:

            raise QgsProcessingException(
                'No se pudo determinar el punto de salida.'
            )

        feedback.pushInfo(
            'Salida automática:'
        )

        feedback.pushInfo(
            'X = {:.3f}'.format(
                salida.x()
            )
        )

        feedback.pushInfo(
            'Y = {:.3f}'.format(
                salida.y()
            )
        )

        feedback.pushInfo(
            'Cota = {:.2f} m'.format(
                cota_salida
            )
        )

        # =====================================================
        # 5. LONGITUD AXIAL
        #
        # SALIDA -> CENTROIDE -> EXTREMO OPUESTO
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '5. Calculando longitud axial...'
        )

        dx = (
            centroide.x() -
            salida.x()
        )

        dy = (
            centroide.y() -
            salida.y()
        )

        modulo = math.hypot(
            dx,
            dy
        )

        if modulo <= 0:

            raise QgsProcessingException(
                'Salida y centroide coinciden.'
            )

        ux = dx / modulo
        uy = dy / modulo

        extremo = None
        distancia_extremo = -1.0

        # -----------------------------------------------------
        # Semiplano opuesto a salida.
        #
        # Dentro de él se busca el punto de divisoria
        # MÁS ALEJADO DEL CENTROIDE.
        # -----------------------------------------------------

        for v in geom_cuenca.vertices():

            p = QgsPointXY(
                v.x(),
                v.y()
            )

            vx = (
                p.x() -
                centroide.x()
            )

            vy = (
                p.y() -
                centroide.y()
            )

            proyeccion = (
                vx * ux +
                vy * uy
            )

            if proyeccion <= 0:
                continue

            d = math.hypot(
                vx,
                vy
            )

            if d > distancia_extremo:

                distancia_extremo = d
                extremo = p

        if extremo is None:

            raise QgsProcessingException(
                'No se pudo determinar el extremo axial.'
            )

        # -----------------------------------------------------
        # LONGITUDES
        # -----------------------------------------------------

        L1_m = self.distancia(
            salida,
            centroide
        )

        L2_m = self.distancia(
            centroide,
            extremo
        )

        Lax_m = (
            L1_m +
            L2_m
        )

        L1_km = L1_m / 1000.0
        L2_km = L2_m / 1000.0
        Lax_km = Lax_m / 1000.0

        # =====================================================
        # 6. PARÁMETROS DE FORMA
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '6. Calculando parámetros de forma...'
        )

        ancho_medio = (
            area_km2 /
            Lax_km
        )

        diametro_equivalente = (
            2.0 *
            math.sqrt(
                area_km2 /
                math.pi
            )
        )

        factor_forma = (
            area_km2 /
            (
                Lax_km ** 2
            )
        )

        kc = (
            0.2820947918 *
            perimetro_km /
            math.sqrt(
                area_km2
            )
        )

        circularidad = (
            4.0 *
            math.pi *
            area_km2 /
            (
                perimetro_km ** 2
            )
        )

        elongacion = (
            diametro_equivalente /
            Lax_km
        )

        # =====================================================
        # 7. ESTADÍSTICAS DEL DEM
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '7. Analizando relieve...'
        )

        stats = dem.dataProvider().bandStatistics(
            1
        )

        elev_min = stats.minimumValue
        elev_max = stats.maximumValue
        elev_media = stats.mean

# =====================================================
        # 8. MEDIANA DEL DEM
        # =====================================================

        feedback.pushInfo(
            'Calculando elevación mediana...'
        )

        elev_mediana = elev_media

        try:

            hist = dem.dataProvider().histogram(
                1,
                1000
            )

            if hist is not None:

                bins = hist.histogramVector

                if bins:

                    total = sum(bins)

                    acumulado = 0

                    hist_min = hist.minimum
                    hist_max = hist.maximum

                    rango = (
                        hist_max -
                        hist_min
                    )

                    if total > 0 and rango > 0:

                        ancho_bin = (
                            rango /
                            len(bins)
                        )

                        for i, n in enumerate(bins):

                            acumulado += n

                            if acumulado >= total / 2.0:

                                elev_mediana = (
                                    hist_min +
                                    (
                                        i + 0.5
                                    ) *
                                    ancho_bin
                                )

                                break

        except Exception as e:

            feedback.pushInfo(
                'Advertencia: no se pudo calcular '
                'la elevación mediana.'
            )

            feedback.pushInfo(
                str(e)
            )

            elev_mediana = elev_media

        # =====================================================
        # 9. DESNIVEL
        # =====================================================

        desnivel = (
            elev_max -
            elev_min
        )

        # =====================================================
        # 10. PENDIENTE MEDIA
        #
        # Creamos raster de pendiente.
        # =====================================================

        feedback.pushInfo(
            'Calculando pendiente media...'
        )

        try:

            pendiente_result = processing.run(
                'gdal:slope',
                {
                    'INPUT': dem,
                    'BAND': 1,
                    'SCALE': 1.0,
                    'AS_PERCENT': True,
                    'COMPUTE_EDGES': True,
                    'ZEVENBERGEN': False,
                    'OPTIONS': '',
                    'EXTRA': '',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context,
                feedback=feedback,
                is_child_algorithm=True
            )

            pendiente_layer = context.getMapLayer(
                pendiente_result['OUTPUT']
            )

            if pendiente_layer is None:

                pendiente_media = float('nan')

            else:

                pendiente_stats = (
                    pendiente_layer
                    .dataProvider()
                    .bandStatistics(1)
                )

                pendiente_media = (
                    pendiente_stats.mean
                )

        except Exception as e:

            feedback.pushInfo(
                'Advertencia: no se pudo calcular '
                'la pendiente media.'
            )

            feedback.pushInfo(
                str(e)
            )

            pendiente_media = float('nan')

        # =====================================================
        # 11. RELACIÓN DE RELIEVE
        #
        # H / Lax
        # =====================================================

        relacion_relieve = (
            desnivel /
            Lax_km
        )

        # Resultado:
        # metros por km

        # =====================================================
        # 12. COEFICIENTE DE MASIVIDAD
        #
        # Cm = Elevación media / Área
        # =====================================================

        coef_masividad = (
            elev_media /
            area_km2
        )

        # m/km²

        # =====================================================
        # 13. COEFICIENTE OROGRÁFICO
        #
        # Co = Hmedia * Cm / 1000
        #
        # Mantiene la misma convención utilizada
        # en nuestro módulo anterior.
        # =====================================================

        coef_orografico = (
            elev_media *
            coef_masividad /
            1000.0
        )

        # =====================================================
        # 14. CREAR PUNTO DE SALIDA
        # =====================================================

        campos_salida = QgsFields()

        campos_salida.append(
            QgsField(
                'ID',
                QVariant.Int
            )
        )

        campos_salida.append(
            QgsField(
                'TIPO',
                QVariant.String
            )
        )

        campos_salida.append(
            QgsField(
                'COTA_m',
                QVariant.Double
            )
        )

        sink_salida, id_salida = self.parameterAsSink(
            parameters,
            self.SALIDA,
            context,
            campos_salida,
            QgsWkbTypes.Point,
            crs
        )

        fs = QgsFeature(
            campos_salida
        )

        fs.setGeometry(
            QgsGeometry.fromPointXY(
                salida
            )
        )

        fs.setAttributes(
            [
                1,
                'SALIDA_AUTO',
                round(
                    cota_salida,
                    2
                )
            ]
        )

        sink_salida.addFeature(
            fs
        )

        # =====================================================
        # 15. CREAR EJE AXIAL
        # =====================================================

        campos_eje = QgsFields()

        campos_eje.append(
            QgsField(
                'ID',
                QVariant.Int
            )
        )

        campos_eje.append(
            QgsField(
                'L1_km',
                QVariant.Double
            )
        )

        campos_eje.append(
            QgsField(
                'L2_km',
                QVariant.Double
            )
        )

        campos_eje.append(
            QgsField(
                'Lax_km',
                QVariant.Double
            )
        )

        sink_eje, id_eje = self.parameterAsSink(
            parameters,
            self.EJE_AXIAL,
            context,
            campos_eje,
            QgsWkbTypes.LineString,
            crs
        )

        fe = QgsFeature(
            campos_eje
        )

        fe.setGeometry(
            QgsGeometry.fromPolylineXY(
                [
                    salida,
                    centroide,
                    extremo
                ]
            )
        )

        fe.setAttributes(
            [
                1,
                round(L1_km, 4),
                round(L2_km, 4),
                round(Lax_km, 4)
            ]
        )

        sink_eje.addFeature(
            fe
        )

        # =====================================================
        # 16. PUNTOS DEL EJE
        # =====================================================

        campos_pts = QgsFields()

        campos_pts.append(
            QgsField(
                'ID',
                QVariant.Int
            )
        )

        campos_pts.append(
            QgsField(
                'TIPO',
                QVariant.String
            )
        )

        sink_pts, id_pts = self.parameterAsSink(
            parameters,
            self.PUNTOS_EJE,
            context,
            campos_pts,
            QgsWkbTypes.Point,
            crs
        )

        def agregar_punto(
            numero,
            tipo,
            punto
        ):

            f = QgsFeature(
                campos_pts
            )

            f.setGeometry(
                QgsGeometry.fromPointXY(
                    punto
                )
            )

            f.setAttributes(
                [
                    numero,
                    tipo
                ]
            )

            sink_pts.addFeature(
                f
            )

        agregar_punto(
            1,
            'SALIDA',
            salida
        )

        agregar_punto(
            2,
            'CENTROIDE',
            centroide
        )

        agregar_punto(
            3,
            'EXTREMO',
            extremo
        )

        # =====================================================
        # 17. CUENCA CON TODOS LOS PARÁMETROS
        # =====================================================

        campos = QgsFields()

        nombres_campos = [
            ('A_km2', QVariant.Double),
            ('P_km', QVariant.Double),

            ('Cx', QVariant.Double),
            ('Cy', QVariant.Double),

            ('L1_km', QVariant.Double),
            ('L2_km', QVariant.Double),
            ('Lax_km', QVariant.Double),

            ('Bmed_km', QVariant.Double),
            ('Deq_km', QVariant.Double),

            ('Ff', QVariant.Double),
            ('Kc', QVariant.Double),
            ('Rc', QVariant.Double),
            ('Re', QVariant.Double),

            ('Zmin_m', QVariant.Double),
            ('Zmax_m', QVariant.Double),
            ('Zmed_m', QVariant.Double),
            ('Zmedian_m', QVariant.Double),

            ('DH_m', QVariant.Double),
            ('Smed_pct', QVariant.Double),

            ('Rr_mkm', QVariant.Double),

            ('Cm_mkm2', QVariant.Double),
            ('Co', QVariant.Double)
        ]

        for nombre, tipo in nombres_campos:

            campos.append(
                QgsField(
                    nombre,
                    tipo
                )
            )

        sink_cuenca, id_cuenca = self.parameterAsSink(
            parameters,
            self.CUENCA_PARAM,
            context,
            campos,
            QgsWkbTypes.MultiPolygon,
            crs
        )

        geom_out = QgsGeometry(
            geom_cuenca
        )

        if QgsWkbTypes.isSingleType(
            geom_out.wkbType()
        ):

            geom_out.convertToMultiType()

        fc = QgsFeature(
            campos
        )

        fc.setGeometry(
            geom_out
        )

        fc.setAttributes(
            [
                round(area_km2, 4),
                round(perimetro_km, 4),

                round(centroide.x(), 3),
                round(centroide.y(), 3),

                round(L1_km, 4),
                round(L2_km, 4),
                round(Lax_km, 4),

                round(ancho_medio, 4),
                round(diametro_equivalente, 4),

                round(factor_forma, 4),
                round(kc, 4),
                round(circularidad, 4),
                round(elongacion, 4),

                round(elev_min, 2),
                round(elev_max, 2),
                round(elev_media, 2),
                round(elev_mediana, 2),

                round(desnivel, 2),

                round(
                    pendiente_media,
                    4
                ) if not math.isnan(
                    pendiente_media
                ) else None,

                round(
                    relacion_relieve,
                    4
                ),

                round(
                    coef_masividad,
                    4
                ),

                round(
                    coef_orografico,
                    4
                )
            ]
        )

        sink_cuenca.addFeature(
            fc
        )

        # =====================================================
        # 18. MOSTRAR RESULTADOS
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '====================================================='
        )
        feedback.pushInfo(
            'RESULTADOS MORFOMÉTRICOS'
        )
        feedback.pushInfo(
            '====================================================='
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- GEOMETRÍA ---'
        )

        feedback.pushInfo(
            'Área = {:.4f} km²'.format(
                area_km2
            )
        )

        feedback.pushInfo(
            'Perímetro = {:.4f} km'.format(
                perimetro_km
            )
        )

        feedback.pushInfo(
            'Centroide X = {:.3f} m'.format(
                centroide.x()
            )
        )

        feedback.pushInfo(
            'Centroide Y = {:.3f} m'.format(
                centroide.y()
            )
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- EJE AXIAL ---'
        )

        feedback.pushInfo(
            'L1 Salida-Centroide = {:.4f} km'.format(
                L1_km
            )
        )

        feedback.pushInfo(
            'L2 Centroide-Extremo = {:.4f} km'.format(
                L2_km
            )
        )

        feedback.pushInfo(
            'LONGITUD AXIAL = {:.4f} km'.format(
                Lax_km
            )
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- FORMA ---'
        )

        feedback.pushInfo(
            'Ancho medio = {:.4f} km'.format(
                ancho_medio
            )
        )

        feedback.pushInfo(
            'Diámetro equivalente = {:.4f} km'.format(
                diametro_equivalente
            )
        )

        feedback.pushInfo(
            'Factor de forma Ff = {:.4f}'.format(
                factor_forma
            )
        )

        feedback.pushInfo(
            'Compacidad Gravelius Kc = {:.4f}'.format(
                kc
            )
        )

        feedback.pushInfo(
            'Circularidad Rc = {:.4f}'.format(
                circularidad
            )
        )

        feedback.pushInfo(
            'Elongación Re = {:.4f}'.format(
                elongacion
            )
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- RELIEVE ---'
        )

        feedback.pushInfo(
            'Elevación mínima = {:.2f} m'.format(
                elev_min
            )
        )

        feedback.pushInfo(
            'Elevación máxima = {:.2f} m'.format(
                elev_max
            )
        )

        feedback.pushInfo(
            'Elevación media = {:.2f} m'.format(
                elev_media
            )
        )

        feedback.pushInfo(
            'Elevación mediana = {:.2f} m'.format(
                elev_mediana
            )
        )

        feedback.pushInfo(
            'Desnivel altitudinal = {:.2f} m'.format(
                desnivel
            )
        )

        if not math.isnan(
            pendiente_media
        ):

            feedback.pushInfo(
                'Pendiente media = {:.4f} %'.format(
                    pendiente_media
                )
            )

        feedback.pushInfo(
            'Relación de relieve = {:.4f} m/km'.format(
                relacion_relieve
            )
        )

        feedback.pushInfo(
            'Coeficiente de masividad = '
            '{:.4f} m/km²'.format(
                coef_masividad
            )
        )

        feedback.pushInfo(
            'Coeficiente orográfico = {:.4f}'.format(
                coef_orografico
            )
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            '====================================================='
        )
        feedback.pushInfo(
            'MÓDULO TERMINADO CORRECTAMENTE'
        )
        feedback.pushInfo(
            '====================================================='
        )

        return {
            self.SALIDA: id_salida,
            self.EJE_AXIAL: id_eje,
            self.PUNTOS_EJE: id_pts,
            self.CUENCA_PARAM: id_cuenca
        }

    # =========================================================
    # INFORMACIÓN
    # =========================================================

    def name(self):

        return 'parametros_cuenca_completo'

    def displayName(self):

        return ('Parámetros I -'
            'Geometría, forma y relieve'
        )

    def group(self):

        return 'HydroROC'

    def groupId(self):

        return 'hidrologia'

    def shortHelpString(self):

        return """
        ====================================
        UNIVERSIDAD NACIONAL DE HUANCAVELICA
        Ing. Richard Oré Cayetano
        964060080-Perú
        ====================================
        MÓDULO I - PARÁMETROS MORFOMÉTRICOS
        Este módulo o herramienta está diseñado para automatizar la caracterización física y geomorfológica de una cuenca hidrográfica a partir de su geometría y su modelo de elevación.
        ENTRADAS:
        - Cuenca delimitada
        - DEM recortado
        
        GEOMETRÍA:
        - Área\Perímetro
        - Centroide
        - Longitud axial
        - Ancho medio
        - Diámetro equivalente

        LONGITUD AXIAL:
        Se determina mediante:
        SALIDA -> CENTROIDE -> EXTREMO OPUESTO
        Lax = L1 + L2


        FORMA:
        - Factor de forma
        - Coeficiente de compacidad de Gravelius
        - Índice de circularidad
        - Relación de elongación

        RELIEVE:
        - Elevación mínima
        - Elevación máxima
        - Elevación media
        - Elevación mediana
        - Desnivel altitudinal
        - Pendiente media
        - Relación de relieve
        - Coeficiente de masividad
        - Coeficiente orográfico

        SALIDAS:
        - Punto de salida automático
        - Eje axial
        - Puntos del eje
        - Cuenca con parámetros
        """

    def createInstance(self):

        return ParametrosCuencaCompleto()