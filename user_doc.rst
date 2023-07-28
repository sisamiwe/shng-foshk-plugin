FOSHK
=====

Anforderungen
-------------
Benötigt wird eine Wetterstation von `Fine Offset Electronics <https://www.foshk.com >`_ mit entsprechender API
oder ein passendes Gateway das die Daten der Wetterstation lokal zur Verfügung stellt.
Die Datenbasis muss *Ecowitt kompatibel* erfolgen.

Getestet wurden GW1000 und WH2650 sowie Froggit DP2000 mit DP1100 7-in-1 Sensor (entspricht GW2000 mit WS90)

Die API ist hier beschrieben: `Data Exchange TCP Protocol for GW1000,1100,1900,2000,2680,2650 <https://osswww.ecowitt.net/uploads/20220407/WN1900%20GW1000,1100%20WH2680,2650%20telenet%20v1.6.4.pdf>`_

Das Plugin bietet die Möglichkeit, die Wetterdaten direkt über die API zu lesen oder die Daten aus dem ECOWITT Protokoll der "Customized Settings" zu beziehen.
Die Einrichtung erfolgt automatisch gemäß den Einstellungen im Plugin.

Konfiguration
-------------

plugin.yaml
^^^^^^^^^^^

Bitte die Dokumentation lesen, die aus den Metadaten der plugin.yaml erzeugt wurde.


items.yaml
^^^^^^^^^^

Bitte die Dokumentation lesen, die aus den Metadaten der plugin.yaml erzeugt wurde.


logic.yaml
^^^^^^^^^^

Bitte die Dokumentation lesen, die aus den Metadaten der plugin.yaml erzeugt wurde.


Funktionen
^^^^^^^^^^

Bitte die Dokumentation lesen, die aus den Metadaten der plugin.yaml erzeugt wurde.


Beispiele
---------

Hier können ausführlichere Beispiele und Anwendungsfälle beschrieben werden.


Web Interface
-------------

FOSHK Items
^^^^^^^^^^^

Das Webinterface zeigt die Items an, für die ein Foshk-Attribut konfiguriert ist.

.. image:: user_doc/assets/webif_tab1.jpg
   :class: screenshot

FOSHK API data
^^^^^^^^^^^^^^

Das Webinterface die verfügbaren Daten (Dict Key und Dict Value) an, die über die API ausgelesen wurden.

.. image:: user_doc/assets/webif_tab2.jpg
   :class: screenshot

FOSHK TCP data
^^^^^^^^^^^^^^

Das Webinterface die verfügbaren Daten (Dict Key und Dict Value) an, die über die TCP-Verbinung und das ECOWITT
Protokoll empfangen.

.. image:: user_doc/assets/webif_tab3.jpg
   :class: screenshot

FOSHK Settings
^^^^^^^^^^^^^^

Das Webinterface die Einstellung der Wetterstation an.

.. image:: user_doc/assets/webif_tab4.jpg
   :class: screenshot

FOSHK Maintenance
^^^^^^^^^^^^^^^^^

Das Webinterface zeigt detaillierte Informationen über die im Plugin verfügbaren Daten an.
Dies dient der Maintenance bzw. Fehlersuche.

.. image:: user_doc/assets/webif_tab5.jpg
   :class: screenshot
