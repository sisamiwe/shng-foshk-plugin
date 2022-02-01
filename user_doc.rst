FOSHK
=====

Anforderungen
-------------
Benötigt wird eine Wetterstation von Fine Offset Electronics mit entsprechender API.
Getestet wurden GW1000 und WH2650.

Die API ist hier beschrieben:

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
