from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterPoint,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterVectorDestination,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsRasterLayer
)

from qgis.PyQt.QtCore import QVariant

import processing
from osgeo import gdal
import numpy as np
import math


class DelimitarCuencaRios(QgsProcessingAlgorithm):

    # =========================================================
    # ENTRADAS
    # =========================================================

    DEM = 'DEM'
    PUNTO = 'PUNTO'
    RADIO = 'RADIO'
    AREA_RIOS = 'AREA_RIOS'

    # =========================================================
    # SALIDAS
    # =========================================================

    CUENCA = 'CUENCA'
    DEM_RECORTADO = 'DEM_RECORTADO'
    RIOS = 'RIOS'
    PUNTO_AJUSTADO = 'PUNTO_AJUSTADO'

    # =========================================================
    # INTERFAZ
    # =========================================================

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.DEM,
                'Modelo Digital de Elevación (DEM)'
            )
        )

        self.addParameter(
            QgsProcessingParameterPoint(
                self.PUNTO,
                'Punto aproximado de salida'
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.RADIO,
                'Radio máximo de ajuste (m)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=100.0,
                minValue=1.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.AREA_RIOS,
                'Área mínima para generar ríos (km²)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.10,
                minValue=0.001
            )
        )

        # -----------------------------------------------------
        # SALIDA: CUENCA
        # -----------------------------------------------------

        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.CUENCA,
                'Cuenca delimitada'
            )
        )

        # -----------------------------------------------------
        # SALIDA: DEM RECORTADO
        # -----------------------------------------------------

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.DEM_RECORTADO,
                'DEM recortado'
            )
        )

        # -----------------------------------------------------
        # SALIDA: RIOS
        # -----------------------------------------------------

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.RIOS,
                'Ríos',
                QgsProcessing.TypeVectorLine
            )
        )

        # -----------------------------------------------------
        # SALIDA: PUNTO
        # -----------------------------------------------------

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PUNTO_AJUSTADO,
                'Punto de salida ajustado',
                QgsProcessing.TypeVectorPoint
            )
        )

    # =========================================================
    # PROCESAMIENTO
    # =========================================================

    def processAlgorithm(self, parameters, context, feedback):

        # =====================================================
        # 1. LEER DEM ORIGINAL
        # =====================================================

        dem = self.parameterAsRasterLayer(
            parameters,
            self.DEM,
            context
        )

        if dem is None:
            raise QgsProcessingException(
                'No se pudo cargar el DEM.'
            )

        crs_dem = dem.crs()

        if crs_dem.isGeographic():

            raise QgsProcessingException(
                'El DEM debe estar en coordenadas proyectadas '
                'en metros, preferentemente UTM.'
            )

        feedback.pushInfo('')
        feedback.pushInfo(
            '=============================================='
        )
        feedback.pushInfo(
            'DELIMITACIÓN DE CUENCA Y GENERACIÓN DE RÍOS'
        )
        feedback.pushInfo(
            '=============================================='
        )

        feedback.pushInfo(
            'DEM: {}'.format(
                dem.name()
            )
        )

        feedback.pushInfo(
            'CRS: {}'.format(
                crs_dem.authid()
            )
        )

        # =====================================================
        # 2. LEER RESOLUCIÓN DEL DEM
        # =====================================================

        ds_dem = gdal.Open(
            dem.source()
        )

        if ds_dem is None:

            raise QgsProcessingException(
                'No se pudo abrir el DEM con GDAL.'
            )

        gt_dem = ds_dem.GetGeoTransform()

        pixel_x = abs(
            gt_dem[1]
        )

        pixel_y = abs(
            gt_dem[5]
        )

        area_celda = (
            pixel_x *
            pixel_y
        )

        ds_dem = None

        feedback.pushInfo('')
        feedback.pushInfo(
            'Resolución DEM: {:.3f} x {:.3f} m'.format(
                pixel_x,
                pixel_y
            )
        )

        # =====================================================
        # 3. LEER PARÁMETROS
        # =====================================================

        radio = self.parameterAsDouble(
            parameters,
            self.RADIO,
            context
        )

        area_rios = self.parameterAsDouble(
            parameters,
            self.AREA_RIOS,
            context
        )

        # =====================================================
        # 4. CONVERTIR ÁREA DE RÍOS A CELDAS
        # =====================================================

        umbral = int(
            round(
                (
                    area_rios *
                    1000000.0
                )
                /
                area_celda
            )
        )

        umbral = max(
            1,
            umbral
        )

        feedback.pushInfo(
            'Área mínima para ríos: {:.4f} km²'.format(
                area_rios
            )
        )

        feedback.pushInfo(
            'Umbral equivalente: {} celdas'.format(
                umbral
            )
        )

        # =====================================================
        # 5. PUNTO DE SALIDA
        # =====================================================

        punto = self.parameterAsPoint(
            parameters,
            self.PUNTO,
            context,
            crs_dem
        )

        punto = QgsPointXY(
            punto
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            'PUNTO INGRESADO'
        )

        feedback.pushInfo(
            'X = {:.3f}'.format(
                punto.x()
            )
        )

        feedback.pushInfo(
            'Y = {:.3f}'.format(
                punto.y()
            )
        )

        # =====================================================
        # 6. CALCULAR ACUMULACIÓN Y DIRECCIÓN
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            'Calculando acumulación y dirección de flujo...'
        )

        watershed = processing.run(

            'grass:r.watershed',

            {
                'elevation':
                    dem,

                'depression':
                    None,

                'blocking':
                    None,

                'threshold':
                    500,

                'convergence':
                    5,

                'memory':
                    300,

                'accumulation':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'drainage':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'basin':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'stream':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'half_basin':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'length_slope':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'slope_steepness':
                    QgsProcessing.TEMPORARY_OUTPUT,

                '-s':
                    False,

                '-m':
                    False,

                '-4':
                    False,

                '-a':
                    False,

                'GRASS_REGION_PARAMETER':
                    dem,

                'GRASS_REGION_CELLSIZE_PARAMETER':
                    0
            },

            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        acumulacion = watershed[
            'accumulation'
        ]

        direccion = watershed[
            'drainage'
        ]

        # =====================================================
        # 7. ABRIR ACUMULACIÓN
        # =====================================================

        ds_acc = gdal.Open(
            acumulacion
        )

        if ds_acc is None:

            raise QgsProcessingException(
                'No se pudo abrir el raster de acumulación.'
            )

        band_acc = ds_acc.GetRasterBand(
            1
        )

        gt_acc = ds_acc.GetGeoTransform()

        x0 = gt_acc[0]
        y0 = gt_acc[3]

        pixel_x_acc = abs(
            gt_acc[1]
        )

        pixel_y_acc = abs(
            gt_acc[5]
        )

        filas_acc = ds_acc.RasterYSize
        columnas_acc = ds_acc.RasterXSize

        # =====================================================
        # 8. POSICIÓN DEL PUNTO EN EL RASTER
        # =====================================================

        col_central = int(
            (
                punto.x() -
                x0
            )
            /
            gt_acc[1]
        )

        fila_central = int(
            (
                punto.y() -
                y0
            )
            /
            gt_acc[5]
        )

        radio_cols = int(
            math.ceil(
                radio /
                pixel_x_acc
            )
        )

        radio_rows = int(
            math.ceil(
                radio /
                pixel_y_acc
            )
        )

        # =====================================================
        # 9. AJUSTAR PUNTO
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            'Ajustando punto al drenaje...'
        )

        mejor_valor = None
        mejor_fila = None
        mejor_col = None
        mejor_distancia = None

        for fila in range(
            fila_central - radio_rows,
            fila_central + radio_rows + 1
        ):

            if (
                fila < 0
                or
                fila >= filas_acc
            ):
                continue

            for col in range(
                col_central - radio_cols,
                col_central + radio_cols + 1
            ):

                if (
                    col < 0
                    or
                    col >= columnas_acc
                ):
                    continue

                # ---------------------------------------------
                # Centro de celda
                # ---------------------------------------------

                x = (
                    x0
                    +
                    (col + 0.5) *
                    gt_acc[1]
                )

                y = (
                    y0
                    +
                    (fila + 0.5) *
                    gt_acc[5]
                )

                # ---------------------------------------------
                # Distancia
                # ---------------------------------------------

                distancia = math.sqrt(
                    (
                        x -
                        punto.x()
                    ) ** 2
                    +
                    (
                        y -
                        punto.y()
                    ) ** 2
                )

                if distancia > radio:
                    continue

                # ---------------------------------------------
                # Acumulación
                # ---------------------------------------------

                dato = band_acc.ReadAsArray(
                    col,
                    fila,
                    1,
                    1
                )

                if dato is None:
                    continue

                valor = float(
                    dato[0][0]
                )

                if not math.isfinite(
                    valor
                ):
                    continue

                valor = abs(
                    valor
                )

                if (
                    mejor_valor is None
                    or
                    valor > mejor_valor
                ):

                    mejor_valor = valor
                    mejor_fila = fila
                    mejor_col = col
                    mejor_distancia = distancia

        # =====================================================
        # 10. VALIDAR PUNTO
        # =====================================================

        if mejor_fila is None:

            ds_acc = None

            raise QgsProcessingException(
                'No se encontró una celda válida '
                'dentro del radio de ajuste.'
            )

        # =====================================================
        # 11. PUNTO AJUSTADO
        # =====================================================

        x_snap = (
            x0
            +
            (mejor_col + 0.5) *
            gt_acc[1]
        )

        y_snap = (
            y0
            +
            (mejor_fila + 0.5) *
            gt_acc[5]
        )

        punto_snap = QgsPointXY(
            x_snap,
            y_snap
        )

        ds_acc = None

        feedback.pushInfo('')
        feedback.pushInfo(
            'PUNTO AJUSTADO'
        )

        feedback.pushInfo(
            'X = {:.3f}'.format(
                x_snap
            )
        )

        feedback.pushInfo(
            'Y = {:.3f}'.format(
                y_snap
            )
        )

        feedback.pushInfo(
            'Desplazamiento = {:.2f} m'.format(
                mejor_distancia
            )
        )

        feedback.pushInfo(
            'Acumulación = {:.0f} celdas'.format(
                mejor_valor
            )
        )

        # =====================================================
        # 12. CREAR PUNTO AJUSTADO
        # =====================================================

        campos_punto = QgsFields()

        campos_punto.append(
            QgsField(
                'X',
                QVariant.Double
            )
        )

        campos_punto.append(
            QgsField(
                'Y',
                QVariant.Double
            )
        )

        campos_punto.append(
            QgsField(
                'Dist_m',
                QVariant.Double
            )
        )

        campos_punto.append(
            QgsField(
                'Acum',
                QVariant.Double
            )
        )

        sink_punto, sink_punto_id = self.parameterAsSink(

            parameters,
            self.PUNTO_AJUSTADO,
            context,

            campos_punto,

            QgsWkbTypes.Point,

            crs_dem
        )

        if sink_punto is None:

            raise QgsProcessingException(
                'No se pudo crear el punto ajustado.'
            )

        feat_punto = QgsFeature(
            campos_punto
        )

        feat_punto.setGeometry(
            QgsGeometry.fromPointXY(
                punto_snap
            )
        )

        feat_punto.setAttributes([
            x_snap,
            y_snap,
            mejor_distancia,
            mejor_valor
        ])

        sink_punto.addFeature(
            feat_punto
        )

        # =====================================================
        # 13. DELIMITAR CUENCA
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            'Delimitando cuenca...'
        )

        outlet = processing.run(

            'grass:r.water.outlet',

            {
                'input':
                    direccion,

                'coordinates':
                    '{},{}'.format(
                        x_snap,
                        y_snap
                    ),

                'output':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'GRASS_REGION_PARAMETER':
                    dem,

                'GRASS_REGION_CELLSIZE_PARAMETER':
                    0
            },

            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        cuenca_raster = outlet[
            'output'
        ]

        # =====================================================
        # 14. POLIGONIZAR CUENCA
        # =====================================================

        feedback.pushInfo(
            'Convirtiendo cuenca a polígono...'
        )

        poligono_temp = processing.run(

            'gdal:polygonize',

            {
                'INPUT':
                    cuenca_raster,

                'BAND':
                    1,

                'FIELD':
                    'DN',

                'EIGHT_CONNECTEDNESS':
                    False,

                'EXTRA':
                    '',

                'OUTPUT':
                    QgsProcessing.TEMPORARY_OUTPUT
            },

            context=context,
            feedback=feedback,
            is_child_algorithm=True

        )['OUTPUT']

        # =====================================================
        # 15. EXTRAER DN = 1
        # =====================================================

        cuenca_extraida = processing.run(

            'native:extractbyexpression',

            {
                'INPUT':
                    poligono_temp,

                'EXPRESSION':
                    '"DN" = 1',

                'OUTPUT':
                    QgsProcessing.TEMPORARY_OUTPUT
            },

            context=context,
            feedback=feedback,
            is_child_algorithm=True

        )['OUTPUT']

        # =====================================================
        # 16. DISOLVER CUENCA
        # =====================================================

        feedback.pushInfo(
            'Generando polígono final de cuenca...'
        )

        cuenca_final = processing.run(

            'native:dissolve',

            {
                'INPUT':
                    cuenca_extraida,

                'FIELD':
                    [],

                'SEPARATE_DISJOINT':
                    False,

                'OUTPUT':
                    parameters[
                        self.CUENCA
                    ]
            },

            context=context,
            feedback=feedback,
            is_child_algorithm=True

        )['OUTPUT']

        # =====================================================
        # 17. RECORTAR DEM
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            'Recortando DEM a la cuenca...'
        )

        dem_recortado_path = processing.run(

            'gdal:cliprasterbymasklayer',

            {
                'INPUT':
                    dem,

                'MASK':
                    cuenca_final,

                'SOURCE_CRS':
                    None,

                'TARGET_CRS':
                    crs_dem,

                'TARGET_EXTENT':
                    None,

                'NODATA':
                    -9999,

                'ALPHA_BAND':
                    False,

                'CROP_TO_CUTLINE':
                    True,

                'KEEP_RESOLUTION':
                    True,

                'SET_RESOLUTION':
                    False,

                'X_RESOLUTION':
                    None,

                'Y_RESOLUTION':
                    None,

                'MULTITHREADING':
                    True,

                'OPTIONS':
                    '',

                'DATA_TYPE':
                    0,

                'EXTRA':
                    '',

                'OUTPUT':
                    parameters[
                        self.DEM_RECORTADO
                    ]
            },

            context=context,
            feedback=feedback,
            is_child_algorithm=True

        )['OUTPUT']

        # =====================================================
        # 18. CARGAR DEM RECORTADO COMO RASTER
        # =====================================================

        dem_recortado = QgsRasterLayer(
            dem_recortado_path,
            'DEM_CUENCA'
        )

        if not dem_recortado.isValid():

            raise QgsProcessingException(
                'El DEM se recortó, pero no pudo cargarse '
                'correctamente para generar los ríos.'
            )

        feedback.pushInfo(
            'DEM recortado cargado correctamente.'
        )

        # =====================================================
        # 19. GENERAR RÍOS SOBRE EL DEM RECORTADO
        #
        # A PARTIR DE AQUÍ SE CONSERVA EL MÉTODO
        # QUE YA FUNCIONÓ EN LA PRUEBA.
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '=============================================='
        )

        feedback.pushInfo(
            'GENERANDO RÍOS'
        )

        feedback.pushInfo(
            '=============================================='
        )

        feedback.pushInfo(
            'Área mínima: {:.4f} km²'.format(
                area_rios
            )
        )

        feedback.pushInfo(
            'Umbral: {} celdas'.format(
                umbral
            )
        )

        resultado_stream = processing.run(

            'grass:r.stream.extract',

            {
                # =============================================
                # IMPORTANTE:
                # AHORA USAMOS EL DEM RECORTADO
                # =============================================

                'elevation':
                    dem_recortado,

                'accumulation':
                    None,

                'depression':
                    None,

                'threshold':
                    umbral,

                'd8cut':
                    0,

                'mexp':
                    0,

                'stream_length':
                    0,

                'stream_raster':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'stream_vector':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'direction':
                    QgsProcessing.TEMPORARY_OUTPUT,

                'GRASS_REGION_PARAMETER':
                    dem_recortado,

                'GRASS_REGION_CELLSIZE_PARAMETER':
                    0
            },

            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        stream_raster = resultado_stream[
            'stream_raster'
        ]

        feedback.pushInfo(
            'Raster de cauces generado.'
        )

        # =====================================================
        # 20. ABRIR STREAM RASTER
        # =====================================================

        ds_stream = gdal.Open(
            stream_raster
        )

        if ds_stream is None:

            raise QgsProcessingException(
                'No se pudo abrir el raster de cauces.'
            )

        band_stream = ds_stream.GetRasterBand(
            1
        )

        arr_stream = band_stream.ReadAsArray()

        gt_stream = ds_stream.GetGeoTransform()

        nodata_stream = band_stream.GetNoDataValue()

        filas_stream = ds_stream.RasterYSize
        columnas_stream = ds_stream.RasterXSize

        # =====================================================
        # 21. IDENTIFICAR CELDAS DE RÍO
        # =====================================================

        if nodata_stream is None:

            mascara = (
                np.isfinite(
                    arr_stream
                )
                &
                (
                    arr_stream != 0
                )
            )

        else:

            mascara = (
                np.isfinite(
                    arr_stream
                )
                &
                (
                    arr_stream != nodata_stream
                )
                &
                (
                    arr_stream != 0
                )
            )

        cantidad_celdas = int(
            np.sum(
                mascara
            )
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            'Celdas de río encontradas: {}'.format(
                cantidad_celdas
            )
        )

        if cantidad_celdas == 0:

            ds_stream = None

            raise QgsProcessingException(
                'No se encontraron celdas de río. '
                'Pruebe reduciendo el área mínima.'
            )

        # =====================================================
        # 22. CREAR DIRECTAMENTE LA SALIDA RÍOS
        #
        # IGUAL QUE EN LA PRUEBA QUE FUNCIONÓ.
        # =====================================================

        campos_rios = QgsFields()

        campos_rios.append(
            QgsField(
                'ID',
                QVariant.Int
            )
        )

        sink_rios, sink_rios_id = self.parameterAsSink(

            parameters,
            self.RIOS,
            context,

            campos_rios,

            QgsWkbTypes.LineString,

            crs_dem
        )

        if sink_rios is None:

            ds_stream = None

            raise QgsProcessingException(
                'No se pudo crear la capa de ríos.'
            )

        # =====================================================
        # 23. CENTRO DE CELDA
        # =====================================================

        def centro(
            fila,
            columna
        ):

            x = (
                gt_stream[0]
                +
                (columna + 0.5)
                *
                gt_stream[1]
                +
                (fila + 0.5)
                *
                gt_stream[2]
            )

            y = (
                gt_stream[3]
                +
                (columna + 0.5)
                *
                gt_stream[4]
                +
                (fila + 0.5)
                *
                gt_stream[5]
            )

            return QgsPointXY(
                x,
                y
            )

        # =====================================================
        # 24. VECINOS
        # =====================================================

        vecinos = [

            (-1, -1),
            (-1,  0),
            (-1,  1),

            ( 0, -1),
            ( 0,  1),

            ( 1, -1),
            ( 1,  0),
            ( 1,  1)
        ]

        # =====================================================
        # 25. CONSTRUIR LÍNEAS
        #
        # MISMO MÉTODO QUE YA FUNCIONÓ.
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            'Construyendo líneas de drenaje...'
        )

        posiciones = np.argwhere(
            mascara
        )

        total = len(
            posiciones
        )

        id_linea = 1
        conexiones = 0

        for i, posicion in enumerate(
            posiciones
        ):

            if feedback.isCanceled():
                break

            fila = int(
                posicion[0]
            )

            col = int(
                posicion[1]
            )

            indice_actual = (
                fila *
                columnas_stream
                +
                col
            )

            p1 = centro(
                fila,
                col
            )

            # -------------------------------------------------
            # Buscar las 8 celdas vecinas
            # -------------------------------------------------

            for df, dc in vecinos:

                f2 = fila + df
                c2 = col + dc

                if (
                    f2 < 0
                    or
                    f2 >= filas_stream
                    or
                    c2 < 0
                    or
                    c2 >= columnas_stream
                ):
                    continue

                if not mascara[
                    f2,
                    c2
                ]:
                    continue

                indice_vecino = (
                    f2 *
                    columnas_stream
                    +
                    c2
                )

                # ---------------------------------------------
                # Evitar duplicar conexiones
                # ---------------------------------------------

                if indice_vecino <= indice_actual:
                    continue

                p2 = centro(
                    f2,
                    c2
                )

                feat_rio = QgsFeature(
                    campos_rios
                )

                feat_rio.setGeometry(
                    QgsGeometry.fromPolylineXY([
                        p1,
                        p2
                    ])
                )

                feat_rio.setAttributes([
                    id_linea
                ])

                # =============================================
                # DIRECTAMENTE A LA SALIDA FINAL
                # =============================================

                sink_rios.addFeature(
                    feat_rio
                )

                id_linea += 1
                conexiones += 1

            # -------------------------------------------------
            # Progreso
            # -------------------------------------------------

            if total > 0:

                feedback.setProgress(
                    int(
                        (
                            i /
                            total
                        )
                        *
                        100
                    )
                )

        ds_stream = None

        # =====================================================
        # 26. COMPROBACIÓN
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            'Celdas de cauce: {}'.format(
                cantidad_celdas
            )
        )

        feedback.pushInfo(
            'Segmentos de río creados: {}'.format(
                conexiones
            )
        )

        if conexiones == 0:

            raise QgsProcessingException(
                'Se detectaron celdas de río, '
                'pero no se pudieron construir las líneas.'
            )

        # =====================================================
        # 27. TERMINADO
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '=============================================='
        )

        feedback.pushInfo(
            'PROCESO TERMINADO'
        )

        feedback.pushInfo(
            '=============================================='
        )

        feedback.pushInfo(
            '✓ CUENCA DELIMITADA'
        )

        feedback.pushInfo(
            '✓ DEM RECORTADO'
        )

        feedback.pushInfo(
            '✓ RÍOS GENERADOS'
        )

        feedback.pushInfo(
            '✓ PUNTO AJUSTADO'
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            'Área mínima de ríos = {:.4f} km²'.format(
                area_rios
            )
        )

        feedback.pushInfo(
            'Número de segmentos = {}'.format(
                conexiones
            )
        )

        # =====================================================
        # RESULTADOS
        # =====================================================

        return {

            self.CUENCA:
                cuenca_final,

            self.DEM_RECORTADO:
                dem_recortado_path,

            self.RIOS:
                sink_rios_id,

            self.PUNTO_AJUSTADO:
                sink_punto_id
        }

    # =========================================================
    # INFORMACIÓN
    # =========================================================

    def name(self):
        return 'delimitar_cuenca_rios_final'

    def displayName(self):
        return 'Delimitación automatica de cuencas.'

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
        DELIMITACIÓN AUTOMÁTICA DE CUENCA, ES UN MODULO DE HydroROC.
        Este plugin o herramienta está diseñado para automatizar el proceso de delimitación de cuencas hidrográficas y la extracción de la red de drenaje a partir de un Modelo Digital de Elevaciones (DEM).

        ENTRADAS

        - Modelo Digital de Elevación (DEM)
        - Punto aproximado de salida(seleccionar sobre el mapa), tambien puede introducirse mediante coordenadas
        - Radio máximo de ajuste (m)
        - Área mínima para generar ríos (km²)

        SALIDAS

        - Cuenca delimitada
        - DEM recortado de la cuenca delimitada
        - Ríos
        - Punto de salida ajustado

        El área mínima para generar los ríos es completamente editable.
        * Un área menor genera más tributarios.
        * Un área mayor conserva principalmente los cauces de mayor importancia.

        El DEM debe encontrarse en un sistema de coordenadas UTM de preferencia.
        """

    def createInstance(self):
        return DelimitarCuencaRios()