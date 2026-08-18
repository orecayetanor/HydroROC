from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterPoint,
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

import math
import heapq
import statistics
from collections import defaultdict


class ParametrosRedDrenajeCompleto(QgsProcessingAlgorithm):

    # =========================================================
    # ENTRADAS
    # =========================================================

    CUENCA = 'CUENCA'
    DEM = 'DEM'
    RIOS = 'RIOS'
    INICIO = 'INICIO'

    # =========================================================
    # SALIDAS
    # =========================================================

    RIOS_ORDENADOS = 'RIOS_ORDENADOS'
    CAUCE_PRINCIPAL = 'CAUCE_PRINCIPAL'
    PUNTOS_CAUCE = 'PUNTOS_CAUCE'
    PARAMETROS = 'PARAMETROS'

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
            QgsProcessingParameterFeatureSource(
                self.RIOS,
                'Ríos - Lines',
                [QgsProcessing.TypeVectorLine]
            )
        )

        # -----------------------------------------------------
        # PUNTO MARCADO DIRECTAMENTE EN EL MAPA
        # -----------------------------------------------------

        self.addParameter(
            QgsProcessingParameterPoint(
                self.INICIO,
                'Marcar inicio del cauce principal'
            )
        )

        # -----------------------------------------------------
        # SALIDAS
        # -----------------------------------------------------

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.RIOS_ORDENADOS,
                'Ríos ordenados - Strahler',
                QgsProcessing.TypeVectorLine
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.CAUCE_PRINCIPAL,
                'Cauce principal',
                QgsProcessing.TypeVectorLine
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PUNTOS_CAUCE,
                'Puntos del cauce principal',
                QgsProcessing.TypeVectorPoint
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PARAMETROS,
                'Cuenca - Parámetros de drenaje',
                QgsProcessing.TypeVectorPolygon
            )
        )

    # =========================================================
    # FUNCIONES AUXILIARES
    # =========================================================

    def distancia(self, p1, p2):

        return math.hypot(
            p2.x() - p1.x(),
            p2.y() - p1.y()
        )

    # ---------------------------------------------------------

    def valor_dem(self, dem, punto):

        try:

            resultado = dem.dataProvider().identify(
                punto,
                QgsRaster.IdentifyFormatValue
            )

            if not resultado.isValid():
                return None

            valores = resultado.results()

            if 1 not in valores:
                return None

            z = valores[1]

            if z is None:
                return None

            z = float(z)

            if not math.isfinite(z):
                return None

            return z

        except:
            return None

    # ---------------------------------------------------------

    def puntos_geometria(self, geom):

        """
        Convierte una geometría lineal en una lista
        de partes formadas por QgsPointXY.
        """

        if geom.isMultipart():

            partes = geom.asMultiPolyline()

            resultado = []

            for parte in partes:

                if len(parte) < 2:
                    continue

                resultado.append(
                    [
                        QgsPointXY(p)
                        for p in parte
                    ]
                )

            return resultado

        else:

            linea = geom.asPolyline()

            if len(linea) < 2:
                return []

            return [
                [
                    QgsPointXY(p)
                    for p in linea
                ]
            ]

    # ---------------------------------------------------------

    def clave(self, punto, tolerancia):

        """
        Agrupa nodos próximos usando una tolerancia
        derivada de la resolución del DEM.
        """

        return (
            int(
                round(
                    punto.x() / tolerancia
                )
            ),
            int(
                round(
                    punto.y() / tolerancia
                )
            )
        )

    # ---------------------------------------------------------

    def reconstruir_geometria(
        self,
        ruta_aristas,
        aristas,
        nodo_inicio
    ):

        puntos_finales = []

        nodo_actual = nodo_inicio

        for numero, idx in enumerate(
            ruta_aristas
        ):

            arista = aristas[idx]

            if arista['n1'] == nodo_actual:

                pts = arista['pts']

                nodo_actual = arista['n2']

            elif arista['n2'] == nodo_actual:

                pts = list(
                    reversed(
                        arista['pts']
                    )
                )

                nodo_actual = arista['n1']

            else:

                raise QgsProcessingException(
                    'Se perdió la continuidad '
                    'durante la reconstrucción del cauce.'
                )

            if numero == 0:

                puntos_finales.extend(
                    pts
                )

            else:

                puntos_finales.extend(
                    pts[1:]
                )

        return puntos_finales

    # =========================================================
    # PROCESAMIENTO
    # =========================================================

    def processAlgorithm(
        self,
        parameters,
        context,
        feedback
    ):

        feedback.pushInfo('')
        feedback.pushInfo(
            '======================================================'
        )
        feedback.pushInfo(
            'MÓDULO 02 - PARÁMETROS DE LA RED DE DRENAJE'
        )
        feedback.pushInfo(
            '======================================================'
        )

        # =====================================================
        # 1. LEER ENTRADAS
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '1. Leyendo información...'
        )

        cuenca = self.parameterAsSource(
            parameters,
            self.CUENCA,
            context
        )

        dem = self.parameterAsRasterLayer(
            parameters,
            self.DEM,
            context
        )

        rios = self.parameterAsSource(
            parameters,
            self.RIOS,
            context
        )

        if cuenca is None:

            raise QgsProcessingException(
                'No se pudo cargar la cuenca.'
            )

        if dem is None:

            raise QgsProcessingException(
                'No se pudo cargar el DEM.'
            )

        if rios is None:

            raise QgsProcessingException(
                'No se pudo cargar Ríos - Lines.'
            )

        crs = rios.sourceCrs()

        if not crs.isValid():

            raise QgsProcessingException(
                'Ríos - Lines no tiene CRS válido.'
            )

        if crs.isGeographic():

            raise QgsProcessingException(
                'Debe utilizar un CRS proyectado en metros.'
            )

        if cuenca.sourceCrs() != crs:

            raise QgsProcessingException(
                'Cuenca y Ríos - Lines deben tener '
                'el mismo CRS.'
            )

        if dem.crs() != crs:

            raise QgsProcessingException(
                'DEM y Ríos - Lines deben tener '
                'el mismo CRS.'
            )

        feedback.pushInfo(
            'CRS = {}'.format(
                crs.authid()
            )
        )

        # =====================================================
        # 2. GEOMETRÍA DE LA CUENCA
        # =====================================================

        geometrias = []

        for f in cuenca.getFeatures():

            if not f.hasGeometry():
                continue

            geom = f.geometry()

            if geom is None or geom.isEmpty():
                continue

            geometrias.append(
                QgsGeometry(geom)
            )

        if not geometrias:

            raise QgsProcessingException(
                'La cuenca no contiene geometría válida.'
            )

        if len(geometrias) == 1:

            geom_cuenca = geometrias[0]

        else:

            geom_cuenca = QgsGeometry.unaryUnion(
                geometrias
            )

        if not geom_cuenca.isGeosValid():

            geom_cuenca = geom_cuenca.makeValid()

        area_km2 = (
            geom_cuenca.area()
            /
            1000000.0
        )

        perimetro_km = (
            geom_cuenca.length()
            /
            1000.0
        )

        if area_km2 <= 0:

            raise QgsProcessingException(
                'El área de la cuenca no es válida.'
            )

        feedback.pushInfo(
            'Área = {:.2f} km²'.format(
                area_km2
            )
        )

        feedback.pushInfo(
            'Perímetro = {:.2f} km'.format(
                perimetro_km
            )
        )

        # =====================================================
        # 3. PUNTO INICIAL MARCADO
        # =====================================================

        punto_marcado = self.parameterAsPoint(
            parameters,
            self.INICIO,
            context,
            crs
        )

        punto_marcado = QgsPointXY(
            punto_marcado
        )

        feedback.pushInfo('')
        feedback.pushInfo(
            '2. Punto inicial marcado:'
        )

        feedback.pushInfo(
            'X = {:.2f}'.format(
                punto_marcado.x()
            )
        )

        feedback.pushInfo(
            'Y = {:.2f}'.format(
                punto_marcado.y()
            )
        )

        # =====================================================
        # 4. TOLERANCIA TOPOLÓGICA
        # =====================================================

        res_x = abs(
            dem.rasterUnitsPerPixelX()
        )

        res_y = abs(
            dem.rasterUnitsPerPixelY()
        )

        resolucion = max(
            res_x,
            res_y
        )

        tolerancia = max(
            resolucion * 0.75,
            0.01
        )

        feedback.pushInfo(
            'Resolución DEM = {:.2f} m'.format(
                resolucion
            )
        )

        feedback.pushInfo(
            'Tolerancia = {:.2f} m'.format(
                tolerancia
            )
        )

        # =====================================================
        # 5. CONSTRUIR RED
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '3. Construyendo red hidrográfica...'
        )

        aristas = []

        nodos_coord = {}

        adyacencia = defaultdict(
            list
        )

        longitud_total_m = 0.0

        for feature in rios.getFeatures():

            if not feature.hasGeometry():
                continue

            geom = feature.geometry()

            if geom is None or geom.isEmpty():
                continue

            partes = self.puntos_geometria(
                geom
            )

            for pts in partes:

                if len(pts) < 2:
                    continue

                for i in range(
                    len(pts) - 1
                ):

                    p1 = pts[i]
                    p2 = pts[i + 1]

                    longitud = self.distancia(
                        p1,
                        p2
                    )

                    if longitud <= 0:
                        continue

                    n1 = self.clave(
                        p1,
                        tolerancia
                    )

                    n2 = self.clave(
                        p2,
                        tolerancia
                    )

                    if n1 == n2:
                        continue

                    if n1 not in nodos_coord:

                        nodos_coord[n1] = p1

                    if n2 not in nodos_coord:

                        nodos_coord[n2] = p2

                    indice = len(
                        aristas
                    )

                    z1 = self.valor_dem(
                        dem,
                        p1
                    )

                    z2 = self.valor_dem(
                        dem,
                        p2
                    )

                    aristas.append(
                        {
                            'n1': n1,
                            'n2': n2,

                            'pts': [
                                p1,
                                p2
                            ],

                            'length':
                                longitud,

                            'z1':
                                z1,

                            'z2':
                                z2,

                            'order':
                                None
                        }
                    )

                    adyacencia[n1].append(
                        (
                            n2,
                            indice,
                            longitud
                        )
                    )

                    adyacencia[n2].append(
                        (
                            n1,
                            indice,
                            longitud
                        )
                    )

                    longitud_total_m += (
                        longitud
                    )

        if not aristas:

            raise QgsProcessingException(
                'No fue posible construir '
                'la red hidrográfica.'
            )

        feedback.pushInfo(
            'Nodos = {}'.format(
                len(nodos_coord)
            )
        )

        feedback.pushInfo(
            'Tramos = {}'.format(
                len(aristas)
            )
        )

        # =====================================================
        # 6. AJUSTAR PUNTO INICIAL
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '4. Ajustando inicio a la red...'
        )

        nodo_inicio = None

        distancia_ajuste = float(
            'inf'
        )

        for nodo, p in nodos_coord.items():

            d = self.distancia(
                punto_marcado,
                p
            )

            if d < distancia_ajuste:

                distancia_ajuste = d

                nodo_inicio = nodo

        if nodo_inicio is None:

            raise QgsProcessingException(
                'No se pudo ajustar el punto '
                'inicial a la red.'
            )

        punto_inicio = nodos_coord[
            nodo_inicio
        ]

        z_inicio = self.valor_dem(
            dem,
            punto_inicio
        )

        feedback.pushInfo(
            'Distancia de ajuste = {:.2f} m'.format(
                distancia_ajuste
            )
        )

        # =====================================================
        # 7. TERMINALES
        # =====================================================

        terminales = []

        for nodo in nodos_coord:

            if len(
                adyacencia[nodo]
            ) == 1:

                terminales.append(
                    nodo
                )

        if not terminales:

            raise QgsProcessingException(
                'No se encontraron extremos '
                'en la red.'
            )

        feedback.pushInfo(
            'Extremos de red = {}'.format(
                len(terminales)
            )
        )

        # =====================================================
        # 8. SALIDA AUTOMÁTICA
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '5. Determinando salida automática...'
        )

        nodo_salida = None

        z_salida = float(
            'inf'
        )

        for nodo in terminales:

            if nodo == nodo_inicio:
                continue

            p = nodos_coord[
                nodo
            ]

            z = self.valor_dem(
                dem,
                p
            )

            if z is None:
                continue

            if z < z_salida:

                z_salida = z

                nodo_salida = nodo

        if nodo_salida is None:

            raise QgsProcessingException(
                'No se pudo determinar '
                'la salida de la red.'
            )

        punto_salida = nodos_coord[
            nodo_salida
        ]

        feedback.pushInfo(
            'Salida X = {:.2f}'.format(
                punto_salida.x()
            )
        )

        feedback.pushInfo(
            'Salida Y = {:.2f}'.format(
                punto_salida.y()
            )
        )

        feedback.pushInfo(
            'Cota salida = {:.2f} m'.format(
                z_salida
            )
        )

        # =====================================================
        # 9. CAUCE PRINCIPAL
        #
        # MANTENEMOS EL MÉTODO QUE YA FUNCIONÓ
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '6. Calculando cauce principal...'
        )

        distancias = {
            nodo_inicio: 0.0
        }

        anterior_nodo = {}

        anterior_arista = {}

        cola = [
            (
                0.0,
                nodo_inicio
            )
        ]

        visitados = set()

        while cola:

            distancia_actual, nodo_actual = (
                heapq.heappop(
                    cola
                )
            )

            if nodo_actual in visitados:
                continue

            visitados.add(
                nodo_actual
            )

            if nodo_actual == nodo_salida:
                break

            for (
                vecino,
                indice_arista,
                longitud
            ) in adyacencia[nodo_actual]:

                if vecino in visitados:
                    continue

                nueva_distancia = (
                    distancia_actual +
                    longitud
                )

                if (
                    vecino not in distancias
                    or
                    nueva_distancia <
                    distancias[vecino]
                ):

                    distancias[vecino] = (
                        nueva_distancia
                    )

                    anterior_nodo[
                        vecino
                    ] = nodo_actual

                    anterior_arista[
                        vecino
                    ] = indice_arista

                    heapq.heappush(
                        cola,
                        (
                            nueva_distancia,
                            vecino
                        )
                    )

        if nodo_salida not in distancias:

            raise QgsProcessingException(
                'No existe una ruta conectada '
                'entre el inicio y la salida.'
            )

        # =====================================================
        # 10. RECONSTRUIR CAUCE
        # =====================================================

        ruta_aristas = []

        nodo = nodo_salida

        while nodo != nodo_inicio:

            if nodo not in anterior_nodo:

                raise QgsProcessingException(
                    'No se pudo reconstruir '
                    'el cauce principal.'
                )

            indice = anterior_arista[
                nodo
            ]

            ruta_aristas.append(
                indice
            )

            nodo = anterior_nodo[
                nodo
            ]

        ruta_aristas.reverse()

        puntos_cauce = self.reconstruir_geometria(
            ruta_aristas,
            aristas,
            nodo_inicio
        )

        if len(puntos_cauce) < 2:

            raise QgsProcessingException(
                'No se pudo generar '
                'la geometría del cauce principal.'
            )

        geom_cauce = QgsGeometry.fromPolylineXY(
            puntos_cauce
        )

        longitud_cauce_m = (
            geom_cauce.length()
        )

        longitud_cauce_km = (
            longitud_cauce_m /
            1000.0
        )

        # =====================================================
        # 11. PARÁMETROS DEL CAUCE PRINCIPAL
        # =====================================================

        distancia_recta_m = self.distancia(
            punto_inicio,
            punto_salida
        )

        distancia_recta_km = (
            distancia_recta_m /
            1000.0
        )

        if z_inicio is not None:

            desnivel_cauce = (
                z_inicio -
                z_salida
            )

        else:

            desnivel_cauce = None

        if (
            desnivel_cauce is not None
            and
            longitud_cauce_m > 0
        ):

            pendiente_cauce_mm = (
                desnivel_cauce /
                longitud_cauce_m
            )

            pendiente_cauce_pct = (
                pendiente_cauce_mm *
                100.0
            )

        else:

            pendiente_cauce_mm = None
            pendiente_cauce_pct = None

        if distancia_recta_m > 0:

            sinuosidad = (
                longitud_cauce_m /
                distancia_recta_m
            )

        else:

            sinuosidad = None


        # =====================================================
        # 12. TIEMPO DE CONCENTRACIÓN - 8 MÉTODOS
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '7. Calculando tiempos de concentración...'
        )

        # Todos los cálculos se realizan con precisión completa.
        # El redondeo a 2 decimales se aplica únicamente al guardar
        # y mostrar los resultados.

        tc_kir_h = None
        tc_tem_h = None
        tc_bw_h = None
        tc_usce_h = None
        tc_cal_h = None
        tc_jc_h = None
        tc_doo_h = None
        tc_hs_h = None

        if (
            longitud_cauce_m > 0
            and
            longitud_cauce_km > 0
            and
            pendiente_cauce_mm is not None
            and
            pendiente_cauce_mm > 0
        ):

            # 1. KIRPICH (1940)
            # Tc(min) = 0.01947 * L(m)^0.77 * S(m/m)^-0.385
            tc_kir_min = (
                0.01947
                *
                (longitud_cauce_m ** 0.77)
                *
                (pendiente_cauce_mm ** -0.385)
            )
            tc_kir_h = tc_kir_min / 60.0

            # 2. TÉMEZ
            # Tc(h) = 0.30 * (L(km) / S(m/m)^0.25)^0.76
            tc_tem_h = (
                0.30
                *
                (
                    longitud_cauce_km
                    /
                    (pendiente_cauce_mm ** 0.25)
                ) ** 0.76
            )
            # 3. BRANSBY-WILLIAMS
            #
            # Tc = (0.2433 * L) / (A^0.1 * S^0.2)
            #
            # Donde:
            # L  = Longitud del cauce principal (km)
            # A  = Área de la cuenca (km²)
            # S  = Pendiente media del cauce (m/m)
            # Tc = Tiempo de concentración (horas)
            tc_bw_h = None

            if (
                longitud_cauce_km > 0
                and
                area_km2 > 0
                and
                pendiente_cauce_mm is not None
                and
                pendiente_cauce_mm > 0
            ):

                tc_bw_h = (
                    0.2433
                    * longitud_cauce_km
                    /
                    (
                        (area_km2 ** 0.1)
                        *
                        (pendiente_cauce_mm ** 0.2)
                    )
                )

            # 4. U.S. CORPS OF ENGINEERS (1954)
            # Tc(h) = 0.191 * L(km)^0.76 * S(m/m)^-0.19
            tc_usce_h = (
                0.191
                *
                (longitud_cauce_km ** 0.76)
                *
                (pendiente_cauce_mm ** -0.19)
            )

            # 6. JOHNSTONE-CROSS (1949)
            # Tc(h) = 0.4623 * L(km)^0.5 * S(m/m)^-0.25
            tc_jc_h = (
                0.4623
                *
                (longitud_cauce_km ** 0.5)
                *
                (pendiente_cauce_mm ** -0.25)
            )

            # 7. DOOGE (1973)
            # Tc(h) = 0.365 * A(km²)^0.41 * S(m/m)^-0.17
            if area_km2 > 0:
                tc_doo_h = (
                    0.365
                    *
                    (area_km2 ** 0.41)
                    *
                    (pendiente_cauce_mm ** -0.17)
                )

            # 8. HAKTANIR-SEZEN (1990)
            # Tc(h) = 0.7473 * L(km)^0.841
            tc_hs_h = (
                0.7473
                *
                (longitud_cauce_km ** 0.841)
            )

        # 5. CALIFORNIA CULVERTS PRACTICE
        # Tc(min) = 0.0195 * (L(m)^3 / H(m))^0.385
        if (
            longitud_cauce_m > 0
            and
            desnivel_cauce is not None
            and
            desnivel_cauce > 0
        ):
            tc_cal_min = (
                0.0195
                *
                (
                    (longitud_cauce_m ** 3)
                    /
                    desnivel_cauce
                ) ** 0.385
            )
            tc_cal_h = tc_cal_min / 60.0

        metodos_tc = [
            ('Kirpich', tc_kir_h),
            ('Témez', tc_tem_h),
            ('Bransby-Williams', tc_bw_h),
            ('U.S. Corps of Engineers', tc_usce_h),
            ('California Culverts', tc_cal_h),
            ('Johnstone-Cross', tc_jc_h),
            ('Dooge', tc_doo_h),
            ('Haktanir-Sezen', tc_hs_h)
        ]

        valores_tc = [
            valor
            for nombre, valor in metodos_tc
            if (
                valor is not None
                and
                math.isfinite(valor)
                and
                valor > 0
            )
        ]

        if valores_tc:

            tc_min_h = min(valores_tc)
            tc_max_h = max(valores_tc)
            tc_prom_h = statistics.mean(valores_tc)
            tc_med_h = statistics.median(valores_tc)

            if len(valores_tc) > 1:
                tc_std_h = statistics.stdev(valores_tc)
            else:
                tc_std_h = 0.0

            if tc_prom_h > 0:
                tc_cv_pct = (
                    tc_std_h
                    /
                    tc_prom_h
                    *
                    100.0
                )
            else:
                tc_cv_pct = None

        else:

            tc_min_h = None
            tc_max_h = None
            tc_prom_h = None
            tc_med_h = None
            tc_std_h = None
            tc_cv_pct = None

        # Tiempo de retardo referencial:
        # Tlag = 0.60 Tc.
        # Se usa la mediana únicamente como referencia estadística.
        if tc_med_h is not None:
            tlag_h = 0.60 * tc_med_h
        else:
            tlag_h = None

        # =====================================================
        # 12. ORIENTAR TODA LA RED HACIA LA SALIDA
        #
        # Calculamos distancia topológica de cada nodo
        # hasta la salida.
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '8. Orientando red hacia la salida...'
        )

        distancia_salida = {
            nodo_salida: 0.0
        }

        cola = [
            (
                0.0,
                nodo_salida
            )
        ]

        while cola:

            d_actual, nodo_actual = (
                heapq.heappop(
                    cola
                )
            )

            if d_actual > distancia_salida.get(
                nodo_actual,
                float('inf')
            ):
                continue

            for (
                vecino,
                indice,
                longitud
            ) in adyacencia[nodo_actual]:

                nueva = (
                    d_actual +
                    longitud
                )

                if (
                    vecino not in distancia_salida
                    or
                    nueva <
                    distancia_salida[vecino]
                ):

                    distancia_salida[
                        vecino
                    ] = nueva

                    heapq.heappush(
                        cola,
                        (
                            nueva,
                            vecino
                        )
                    )

        # =====================================================
        # 13. DIRECCIÓN DE CADA ARISTA
        # =====================================================

        entrantes = defaultdict(
            list
        )

        salientes = defaultdict(
            list
        )

        for i, arista in enumerate(
            aristas
        ):

            n1 = arista['n1']
            n2 = arista['n2']

            d1 = distancia_salida.get(
                n1,
                float('inf')
            )

            d2 = distancia_salida.get(
                n2,
                float('inf')
            )

            # El nodo con mayor distancia a salida
            # se considera aguas arriba.

            if d1 >= d2:

                up = n1
                down = n2

            else:

                up = n2
                down = n1

            arista['up'] = up
            arista['down'] = down

            salientes[
                up
            ].append(i)

            entrantes[
                down
            ].append(i)

        # =====================================================
        # 14. STRAHLER
        # =====================================================

        feedback.pushInfo(
            'Calculando orden de Strahler...'
        )

        ordenes = [
            None
            for _ in aristas
        ]

        max_iter = (
            len(aristas) * 5
            +
            100
        )

        for _ in range(
            max_iter
        ):

            cambios = False

            for i, arista in enumerate(
                aristas
            ):

                if ordenes[i] is not None:
                    continue

                nodo_up = arista[
                    'up'
                ]

                tributarios = entrantes.get(
                    nodo_up,
                    []
                )

                if not tributarios:

                    ordenes[i] = 1

                    cambios = True

                    continue

                ordenes_tributarios = [
                    ordenes[j]
                    for j in tributarios
                ]

                if any(
                    o is None
                    for o in ordenes_tributarios
                ):
                    continue

                max_orden = max(
                    ordenes_tributarios
                )

                cantidad = (
                    ordenes_tributarios.count(
                        max_orden
                    )
                )

                if cantidad >= 2:

                    ordenes[i] = (
                        max_orden + 1
                    )

                else:

                    ordenes[i] = (
                        max_orden
                    )

                cambios = True

            if not cambios:
                break

        no_resueltos = 0

        for i in range(
            len(ordenes)
        ):

            if ordenes[i] is None:

                ordenes[i] = 1

                no_resueltos += 1

            aristas[i][
                'order'
            ] = ordenes[i]

        if no_resueltos > 0:

            feedback.pushInfo(
                'Advertencia: {} tramos no pudieron '
                'resolverse topológicamente.'
                .format(
                    no_resueltos
                )
            )

        orden_maximo = max(
            ordenes
        )

        # =====================================================
        # 15. ESTADÍSTICAS POR ORDEN
        # =====================================================

        numero_por_orden = defaultdict(
            int
        )

        longitud_por_orden = defaultdict(
            float
        )

        for arista in aristas:

            orden = arista[
                'order'
            ]

            numero_por_orden[
                orden
            ] += 1

            longitud_por_orden[
                orden
            ] += arista[
                'length'
            ]

        # =====================================================
        # 16. RAZÓN DE BIFURCACIÓN
        # =====================================================

        rb_lista = []

        for orden in range(
            1,
            orden_maximo
        ):

            Nu = numero_por_orden[
                orden
            ]

            Nu1 = numero_por_orden[
                orden + 1
            ]

            if Nu1 > 0:

                rb_lista.append(
                    Nu / Nu1
                )

        if rb_lista:

            rb_media = (
                sum(rb_lista)
                /
                len(rb_lista)
            )

        else:

            rb_media = 0.0

        # =====================================================
        # 17. RAZÓN DE LONGITUD
        # =====================================================

        longitud_media_orden = {}

        for orden in range(
            1,
            orden_maximo + 1
        ):

            n = numero_por_orden[
                orden
            ]

            if n > 0:

                longitud_media_orden[
                    orden
                ] = (
                    longitud_por_orden[
                        orden
                    ]
                    /
                    n
                )

        rl_lista = []

        for orden in range(
            1,
            orden_maximo
        ):

            if (
                orden in longitud_media_orden
                and
                orden + 1 in longitud_media_orden
                and
                longitud_media_orden[orden] > 0
            ):

                rl_lista.append(
                    longitud_media_orden[
                        orden + 1
                    ]
                    /
                    longitud_media_orden[
                        orden
                    ]
                )

        if rl_lista:

            rl_media = (
                sum(rl_lista)
                /
                len(rl_lista)
            )

        else:

            rl_media = 0.0

        # =====================================================
        # 18. PARÁMETROS GENERALES
        # =====================================================

        longitud_total_km = (
            longitud_total_m /
            1000.0
        )

        numero_tramos = len(
            aristas
        )

        longitud_media_km = (
            longitud_total_km /
            numero_tramos
        )

        # -----------------------------------------------------
        # DENSIDAD DE DRENAJE
        # Dd = Lt / A
        # -----------------------------------------------------

        densidad_drenaje = (
            longitud_total_km /
            area_km2
        )

        # -----------------------------------------------------
        # FRECUENCIA
        # Fs = N / A
        # -----------------------------------------------------

        frecuencia_corrientes = (
            numero_tramos /
            area_km2
        )

        # -----------------------------------------------------
        # TEXTURA
        # Rt = N / P
        # -----------------------------------------------------

        textura_drenaje = (
            numero_tramos /
            perimetro_km
        )

        # -----------------------------------------------------
        # CONSTANTE DE MANTENIMIENTO
        # C = 1 / Dd
        # -----------------------------------------------------

        if densidad_drenaje > 0:

            constante_mantenimiento = (
                1.0 /
                densidad_drenaje
            )

        else:

            constante_mantenimiento = 0.0

        # -----------------------------------------------------
        # LONGITUD DE FLUJO SUPERFICIAL
        # Lo = 1 / (2 Dd)
        # -----------------------------------------------------

        if densidad_drenaje > 0:

            longitud_flujo = (
                1.0 /
                (
                    2.0 *
                    densidad_drenaje
                )
            )

        else:

            longitud_flujo = 0.0

        # =====================================================
        # 19. CREAR RÍOS ORDENADOS
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '8. Generando capas de salida...'
        )

        campos_rios = QgsFields()

        campos_rios.append(
            QgsField(
                'ID',
                QVariant.Int
            )
        )

        campos_rios.append(
            QgsField(
                'ORDEN',
                QVariant.Int
            )
        )

        campos_rios.append(
            QgsField(
                'LONG_KM',
                QVariant.Double
            )
        )

        campos_rios.append(
            QgsField(
                'PRINCIPAL',
                QVariant.Int
            )
        )

        sink_rios, id_rios = self.parameterAsSink(
            parameters,
            self.RIOS_ORDENADOS,
            context,
            campos_rios,
            QgsWkbTypes.LineString,
            crs
        )

        if sink_rios is None:

            raise QgsProcessingException(
                'No se pudo crear '
                'Ríos ordenados.'
            )

        ruta_set = set(
            ruta_aristas
        )

        for i, arista in enumerate(
            aristas
        ):

            f = QgsFeature(
                campos_rios
            )

            f.setGeometry(
                QgsGeometry.fromPolylineXY(
                    arista['pts']
                )
            )

            f.setAttributes(
                [
                    i + 1,

                    arista[
                        'order'
                    ],

                    round(
                        arista[
                            'length'
                        ]
                        /
                        1000.0,
                        2
                    ),

                    1 if i in ruta_set else 0
                ]
            )

            sink_rios.addFeature(
                f
            )

        # =====================================================
        # 20. CREAR CAUCE PRINCIPAL
        # =====================================================

        campos_cauce = QgsFields()

        lista_campos_cauce = [

            ('ID', QVariant.Int),
            ('LONG_KM', QVariant.Double),
            ('RECTA_KM', QVariant.Double),

            ('Z_INI', QVariant.Double),
            ('Z_FIN', QVariant.Double),

            ('DESN_M', QVariant.Double),

            ('PEND_PCT', QVariant.Double),
            ('PEND_MM', QVariant.Double),

            ('SINUOS', QVariant.Double),

            ('TC_KIR_H', QVariant.Double),
            ('TC_TEM_H', QVariant.Double),
            ('TC_BW_H', QVariant.Double),
            ('TC_USCE_H', QVariant.Double),
            ('TC_CAL_H', QVariant.Double),
            ('TC_JC_H', QVariant.Double),
            ('TC_DOO_H', QVariant.Double),
            ('TC_HS_H', QVariant.Double)
        ]

        for nombre, tipo in lista_campos_cauce:

            campos_cauce.append(
                QgsField(
                    nombre,
                    tipo
                )
            )

        sink_cauce, id_cauce = self.parameterAsSink(
            parameters,
            self.CAUCE_PRINCIPAL,
            context,
            campos_cauce,
            QgsWkbTypes.LineString,
            crs
        )

        if sink_cauce is None:

            raise QgsProcessingException(
                'No se pudo crear '
                'Cauce principal.'
            )

        f = QgsFeature(
            campos_cauce
        )

        f.setGeometry(
            geom_cauce
        )

        f.setAttributes(
            [
                1,

                round(
                    longitud_cauce_km,
                    2
                ),

                round(
                    distancia_recta_km,
                    2
                ),

                round(
                    z_inicio,
                    2
                ) if z_inicio is not None else None,

                round(
                    z_salida,
                    2
                ),

                round(
                    desnivel_cauce,
                    2
                ) if desnivel_cauce is not None else None,

                round(
                    pendiente_cauce_pct,
                    2
                ) if pendiente_cauce_pct is not None else None,

                round(
                    pendiente_cauce_mm,
                    2
                ) if pendiente_cauce_mm is not None else None,

                round(
                    sinuosidad,
                    2
                ) if sinuosidad is not None else None,

                round(tc_kir_h, 2) if tc_kir_h is not None else None,
                round(tc_tem_h, 2) if tc_tem_h is not None else None,
                round(tc_bw_h, 2) if tc_bw_h is not None else None,
                round(tc_usce_h, 2) if tc_usce_h is not None else None,
                round(tc_cal_h, 2) if tc_cal_h is not None else None,
                round(tc_jc_h, 2) if tc_jc_h is not None else None,
                round(tc_doo_h, 2) if tc_doo_h is not None else None,
                round(tc_hs_h, 2) if tc_hs_h is not None else None
            ]
        )

        sink_cauce.addFeature(
            f
        )

        # =====================================================
        # 21. PUNTOS DEL CAUCE
        # =====================================================

        campos_puntos = QgsFields()

        campos_puntos.append(
            QgsField(
                'ID',
                QVariant.Int
            )
        )

        campos_puntos.append(
            QgsField(
                'TIPO',
                QVariant.String
            )
        )

        campos_puntos.append(
            QgsField(
                'COTA_M',
                QVariant.Double
            )
        )

        sink_puntos, id_puntos = self.parameterAsSink(
            parameters,
            self.PUNTOS_CAUCE,
            context,
            campos_puntos,
            QgsWkbTypes.Point,
            crs
        )

        def agregar_punto(
            identificador,
            tipo,
            punto,
            cota
        ):

            f = QgsFeature(
                campos_puntos
            )

            f.setGeometry(
                QgsGeometry.fromPointXY(
                    punto
                )
            )

            f.setAttributes(
                [
                    identificador,
                    tipo,
                    cota
                ]
            )

            sink_puntos.addFeature(
                f
            )

        agregar_punto(
            1,
            'MARCADO',
            punto_marcado,
            self.valor_dem(
                dem,
                punto_marcado
            )
        )

        agregar_punto(
            2,
            'INICIO',
            punto_inicio,
            z_inicio
        )

        agregar_punto(
            3,
            'SALIDA',
            punto_salida,
            z_salida
        )

        # =====================================================
        # 22. CUENCA CON PARÁMETROS
        # =====================================================

        campos_param = QgsFields()

        lista_parametros = [

            ('A_KM2', QVariant.Double),

            ('N_TRAMOS', QVariant.Int),

            ('LT_KM', QVariant.Double),

            ('LM_KM', QVariant.Double),

            ('DD', QVariant.Double),

            ('FS', QVariant.Double),

            ('RT', QVariant.Double),

            ('C_MANT', QVariant.Double),

            ('LO_KM', QVariant.Double),

            ('ORD_MAX', QVariant.Int),

            ('RB_MED', QVariant.Double),

            ('RL_MED', QVariant.Double),

            ('LC_KM', QVariant.Double),

            ('LRECT_KM', QVariant.Double),

            ('ZCAB_M', QVariant.Double),

            ('ZSAL_M', QVariant.Double),

            ('DH_CAUCE', QVariant.Double),

            ('SC_PCT', QVariant.Double),

            ('SC_MM', QVariant.Double),

            ('SINUOS', QVariant.Double),

            ('TC_KIR_H', QVariant.Double),
            ('TC_TEM_H', QVariant.Double),
            ('TC_BW_H', QVariant.Double),
            ('TC_USCE_H', QVariant.Double),
            ('TC_CAL_H', QVariant.Double),
            ('TC_JC_H', QVariant.Double),
            ('TC_DOO_H', QVariant.Double),
            ('TC_HS_H', QVariant.Double),

            ('TC_MIN_H', QVariant.Double),
            ('TC_MAX_H', QVariant.Double),
            ('TC_PROM_H', QVariant.Double),
            ('TC_MED_H', QVariant.Double),
            ('TC_STD_H', QVariant.Double),
            ('TC_CV_PCT', QVariant.Double),
            ('TLAG_H', QVariant.Double)
        ]

        for nombre, tipo in lista_parametros:

            campos_param.append(
                QgsField(
                    nombre,
                    tipo
                )
            )

        sink_param, id_param = self.parameterAsSink(
            parameters,
            self.PARAMETROS,
            context,
            campos_param,
            QgsWkbTypes.MultiPolygon,
            crs
        )

        if sink_param is None:

            raise QgsProcessingException(
                'No se pudo crear '
                'la capa de parámetros.'
            )

        geom_out = QgsGeometry(
            geom_cuenca
        )

        if QgsWkbTypes.isSingleType(
            geom_out.wkbType()
        ):

            geom_out.convertToMultiType()

        f = QgsFeature(
            campos_param
        )

        f.setGeometry(
            geom_out
        )

        f.setAttributes(
            [
                round(
                    area_km2,
                    2
                ),

                numero_tramos,

                round(
                    longitud_total_km,
                    2
                ),

                round(
                    longitud_media_km,
                    2
                ),

                round(
                    densidad_drenaje,
                    2
                ),

                round(
                    frecuencia_corrientes,
                    2
                ),

                round(
                    textura_drenaje,
                    2
                ),

                round(
                    constante_mantenimiento,
                    2
                ),

                round(
                    longitud_flujo,
                    2
                ),

                orden_maximo,

                round(
                    rb_media,
                    2
                ),

                round(
                    rl_media,
                    2
                ),

                round(
                    longitud_cauce_km,
                    2
                ),

                round(
                    distancia_recta_km,
                    2
                ),

                round(
                    z_inicio,
                    2
                ) if z_inicio is not None else None,

                round(
                    z_salida,
                    2
                ),

                round(
                    desnivel_cauce,
                    2
                ) if desnivel_cauce is not None else None,

                round(
                    pendiente_cauce_pct,
                    2
                ) if pendiente_cauce_pct is not None else None,

                round(
                    pendiente_cauce_mm,
                    2
                ) if pendiente_cauce_mm is not None else None,

                round(
                    sinuosidad,
                    2
                ) if sinuosidad is not None else None,

                round(tc_kir_h, 2) if tc_kir_h is not None else None,
                round(tc_tem_h, 2) if tc_tem_h is not None else None,
                round(tc_bw_h, 2) if tc_bw_h is not None else None,
                round(tc_usce_h, 2) if tc_usce_h is not None else None,
                round(tc_cal_h, 2) if tc_cal_h is not None else None,
                round(tc_jc_h, 2) if tc_jc_h is not None else None,
                round(tc_doo_h, 2) if tc_doo_h is not None else None,
                round(tc_hs_h, 2) if tc_hs_h is not None else None,

                round(tc_min_h, 2) if tc_min_h is not None else None,
                round(tc_max_h, 2) if tc_max_h is not None else None,
                round(tc_prom_h, 2) if tc_prom_h is not None else None,
                round(tc_med_h, 2) if tc_med_h is not None else None,
                round(tc_std_h, 2) if tc_std_h is not None else None,
                round(tc_cv_pct, 2) if tc_cv_pct is not None else None,
                round(tlag_h, 2) if tlag_h is not None else None
            ]
        )

        sink_param.addFeature(
            f
        )

        # =====================================================
        # 23. RESULTADOS
        # =====================================================

        feedback.pushInfo('')
        feedback.pushInfo(
            '======================================================'
        )
        feedback.pushInfo(
            'RESULTADOS - MÓDULO 02'
        )
        feedback.pushInfo(
            '======================================================'
        )

        # -----------------------------------------------------
        # RED GENERAL
        # -----------------------------------------------------

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- RED DE DRENAJE ---'
        )

        feedback.pushInfo(
            'Área = {:.2f} km²'.format(
                area_km2
            )
        )

        feedback.pushInfo(
            'Número de tramos = {}'.format(
                numero_tramos
            )
        )

        feedback.pushInfo(
            'Longitud total = {:.2f} km'.format(
                longitud_total_km
            )
        )

        feedback.pushInfo(
            'Longitud media = {:.2f} km'.format(
                longitud_media_km
            )
        )

        feedback.pushInfo(
            'Densidad de drenaje = {:.2f} km/km²'.format(
                densidad_drenaje
            )
        )

        feedback.pushInfo(
            'Frecuencia de corrientes = {:.2f} 1/km²'.format(
                frecuencia_corrientes
            )
        )

        feedback.pushInfo(
            'Textura de drenaje = {:.2f} 1/km'.format(
                textura_drenaje
            )
        )

        feedback.pushInfo(
            'Constante de mantenimiento = {:.2f} km'.format(
                constante_mantenimiento
            )
        )

        feedback.pushInfo(
            'Longitud flujo superficial = {:.2f} km'.format(
                longitud_flujo
            )
        )

        # -----------------------------------------------------
        # STRAHLER
        # -----------------------------------------------------

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- ORDEN DE STRAHLER ---'
        )

        feedback.pushInfo(
            'Orden máximo = {}'.format(
                orden_maximo
            )
        )

        for orden in range(
            1,
            orden_maximo + 1
        ):

            feedback.pushInfo(
                'Orden {}: N = {} | L = {:.2f} km'.format(
                    orden,

                    numero_por_orden[
                        orden
                    ],

                    longitud_por_orden[
                        orden
                    ] / 1000.0
                )
            )

        feedback.pushInfo(
            'Razón de bifurcación media = {:.2f}'.format(
                rb_media
            )
        )

        feedback.pushInfo(
            'Razón de longitud media = {:.2f}'.format(
                rl_media
            )
        )

        # -----------------------------------------------------
        # CAUCE PRINCIPAL
        # -----------------------------------------------------

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- CAUCE PRINCIPAL ---'
        )

        feedback.pushInfo(
            'Longitud real = {:.2f} km'.format(
                longitud_cauce_km
            )
        )

        feedback.pushInfo(
            'Longitud recta = {:.2f} km'.format(
                distancia_recta_km
            )
        )

        if z_inicio is not None:

            feedback.pushInfo(
                'Cota cabecera = {:.2f} m'.format(
                    z_inicio
                )
            )

        feedback.pushInfo(
            'Cota salida = {:.2f} m'.format(
                z_salida
            )
        )

        if desnivel_cauce is not None:

            feedback.pushInfo(
                'Desnivel = {:.2f} m'.format(
                    desnivel_cauce
                )
            )

            feedback.pushInfo(
                'Pendiente media = {:.2f} %'.format(
                    pendiente_cauce_pct
                )
            )

            feedback.pushInfo(
                'Pendiente media = {:.2f} m/m'.format(
                    pendiente_cauce_mm
                )
            )

        if sinuosidad is not None:

            feedback.pushInfo(
                'Sinuosidad = {:.2f}'.format(
                    sinuosidad
                )
            )


        # -----------------------------------------------------
        # TIEMPOS DE CONCENTRACIÓN
        # -----------------------------------------------------

        feedback.pushInfo('')
        feedback.pushInfo(
            '--- TIEMPO DE CONCENTRACIÓN ---'
        )

        for numero, (nombre, valor) in enumerate(
            metodos_tc,
            start=1
        ):

            if valor is not None:

                feedback.pushInfo(
                    '{}. {} = {:.2f} h | {:.2f} min'.format(
                        numero,
                        nombre,
                        valor,
                        valor * 60.0
                    )
                )

            else:

                feedback.pushInfo(
                    '{}. {} = NO CALCULADO'.format(
                        numero,
                        nombre
                    )
                )

        feedback.pushInfo('')

        if tc_min_h is not None:
            feedback.pushInfo(
                'Tc mínimo = {:.2f} h'.format(tc_min_h)
            )

        if tc_max_h is not None:
            feedback.pushInfo(
                'Tc máximo = {:.2f} h'.format(tc_max_h)
            )

        if tc_prom_h is not None:
            feedback.pushInfo(
                'Tc promedio = {:.2f} h'.format(tc_prom_h)
            )

        if tc_med_h is not None:
            feedback.pushInfo(
                'Tc mediana = {:.2f} h'.format(tc_med_h)
            )

        if tc_std_h is not None:
            feedback.pushInfo(
                'Desviación estándar = {:.2f} h'.format(tc_std_h)
            )

        if tc_cv_pct is not None:
            feedback.pushInfo(
                'Coeficiente de variación = {:.2f} %'.format(
                    tc_cv_pct
                )
            )

        if tlag_h is not None:
            feedback.pushInfo(
                'Tlag referencial (0.60 x Tc mediana) = {:.2f} h'.format(
                    tlag_h
                )
            )

        feedback.pushInfo('')
        feedback.pushInfo(
            '======================================================'
        )
        feedback.pushInfo(
            'MÓDULO 02 TERMINADO CORRECTAMENTE'
        )
        feedback.pushInfo(
            '======================================================'
        )

        return {

            self.RIOS_ORDENADOS:
                id_rios,

            self.CAUCE_PRINCIPAL:
                id_cauce,

            self.PUNTOS_CAUCE:
                id_puntos,

            self.PARAMETROS:
                id_param
        }

    # =========================================================
    # INFORMACIÓN
    # =========================================================

    def name(self):

        return 'parametros_red_drenaje_completo'

    def displayName(self):

        return ('Parámetros II - Red de drenaje, Tiempo de Concentración'
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
        MÓDULO II - RED DE DRENAJE
        Este módulo o herramienta está diseñado para analizar la red hídrica, jerarquizar los cauces y calcular el tiempo de concentración de la cuenca de forma completamente automatizada.
        ENTRADAS:

        - Cuenca delimitada
        - DEM recortado
        - Ríos - Lines
        - Marcar inicio del cauce principal en el mapa


        PARÁMETROS DE RED:

        - Número de tramos
        - Longitud total
        - Longitud media
        - Densidad de drenaje
        - Frecuencia de corrientes
        - Textura de drenaje
        - Constante de mantenimiento
        - Longitud de flujo superficial


        JERARQUÍA:

        - Orden de Strahler
        - Orden máximo
        - Número de tramos por orden
        - Longitud por orden
        - Razón de bifurcación
        - Razón de longitud


        CAUCE PRINCIPAL:

        - Longitud real
        - Longitud recta
        - Cota inicial
        - Cota final
        - Desnivel
        - Pendiente media
        - Sinuosidad


        TIEMPO DE CONCENTRACIÓN:

        1. Kirpich
        2. Témez
        3. Bransby-Williams
        4. U.S. Corps of Engineers
        5. California Culverts Practice
        6. Johnstone-Cross
        7. Dooge
        8. Haktanir-Sezen

        También calcula:
        - Tc mínimo
        - Tc máximo
        - Tc promedio
        - Tc mediana
        - Desviación estándar
        - Coeficiente de variación
        - Tlag referencial = 0.60 x Tc mediana


        SALIDAS:

        - Ríos ordenados - Strahler
        - Cauce principal
        - Puntos del cauce principal
        - Cuenca con parámetros de drenaje
        """

    def createInstance(self):

        return ParametrosRedDrenajeCompleto()